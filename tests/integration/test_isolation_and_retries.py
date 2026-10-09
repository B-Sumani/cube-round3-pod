"""Review findings, each pinned by a test (docs/decisions.md D-111..D-114).

* An in-process agent (or a timed-out thread still running) must not be able to change stored evidence or workflow
  state through the objects it was handed.
* A retry after an in-process timeout must not start a second concurrent execution of the same request.
* A store refusal (immutability conflict, unsafe id, tenancy) on an agent's output is recorded, not a crash.
* An agent calling sys.exit() must not take the orchestrator down.
* The API refuses ambiguous tenant / subject ids instead of answering 500.
"""
import copy
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestration.clients import InProcClient
from orchestration.orchestrator import load_flow, run_workflow, workflow_id_for
from orchestration.store import FileStore, MemoryStore
from shared.utils.hashing import verify
from tests.helpers import Fake

ROOT = Path(__file__).resolve().parents[2]
STANDARD = load_flow(ROOT / "orchestration/flow.json")
CASE = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True}


def flow(**defaults):
    return {**STANDARD, "defaults": {**STANDARD["defaults"], **defaults}}


def inproc(handle):
    return InProcClient(handle=handle)


def snapshot(store, wf):
    return copy.deepcopy({rid: store.get_evidence(rid, wf["org_id"]) for rid in wf["evidence_references"]})


# ------------------------------------------------------------ A. inputs are copies, stored evidence is not shared
def vandal(request):
    """Mutates everything it was handed, then answers normally."""
    for rec in request["previous_evidence"]:
        rec["checks"].clear()
        rec["decision"]["verdict"] = "FAIL"
    request["context"]["overrides"].append({"forged": True})
    out = Fake("PASS").run(request, 0)
    return out


def test_an_agent_mutating_its_input_cannot_touch_stored_evidence_or_state():
    store = MemoryStore()
    wf = run_workflow(CASE, STANDARD, store, {"prep": inproc(vandal)})
    receiving = store.get_evidence(wf["stage_results"][0]["record_id"], CASE["org_id"])
    assert verify(receiving) and receiving["checks"], "stored evidence unchanged"
    assert wf["overrides"] == [] and store.load_workflow(wf["workflow_id"], CASE["org_id"])["overrides"] == []
    assert wf["status"] == "COMPLETED"


def test_a_timed_out_agent_cannot_change_anything_after_the_orchestrator_moved_on():
    released = threading.Event()

    def late_vandal(request):
        released.wait(5)
        return vandal(request)

    store = MemoryStore()
    wf = run_workflow(CASE, flow(timeout_s=0.1, retries=0), store, {"prep": inproc(late_vandal)})
    assert wf["status"] == "FAILED"
    before, saved = snapshot(store, wf), store.load_workflow(wf["workflow_id"], CASE["org_id"])
    released.set()
    time.sleep(0.3)  # the orphaned thread finishes and vandalises its copy
    assert snapshot(store, wf) == before and store.load_workflow(wf["workflow_id"], CASE["org_id"]) == saved
    assert all(verify(r) for r in before.values())


def test_a_returned_record_kept_by_the_agent_cannot_be_edited_after_storage():
    kept = {}

    def keeper(request):
        out = Fake("PASS").run(request, 0)
        kept["ev"] = out["evidence"]
        return out

    store = MemoryStore()
    wf = run_workflow(CASE, STANDARD, store, {"prep": inproc(keeper)})
    kept["ev"]["decision"]["verdict"] = "FAIL"
    assert verify(store.get_evidence(kept["ev"]["record_id"], CASE["org_id"]))


# ------------------------------------------------------------ B. no duplicate concurrent executions on retry
def test_retry_after_timeout_rejoins_the_running_attempt_instead_of_starting_another():
    calls = []

    def slow(request):
        calls.append(request["request_id"])
        time.sleep(0.5)
        return Fake("PASS").run(request, 0)

    wf = run_workflow(CASE, flow(timeout_s=0.2, retries=3), MemoryStore(), {"prep": inproc(slow)})
    sr = next(s for s in wf["stage_results"] if s["stage"] == "prep")
    assert len(calls) == 1, "one execution, however many attempts"
    assert sr["state"] == "completed" and sr["attempts"] >= 3


def test_a_resume_after_timeout_is_a_new_request_and_may_run_again():
    calls = []

    def slow_once(request):
        calls.append(request["request_id"])
        if len(calls) == 1:
            time.sleep(0.6)
        return Fake("PASS").run(request, 0)

    store = MemoryStore()
    clients = {"prep": inproc(slow_once)}
    wf = run_workflow(CASE, flow(timeout_s=0.1, retries=0), store, clients)
    assert wf["status"] == "FAILED"
    from orchestration.orchestrator import resume
    wf = resume(wf["workflow_id"], flow(timeout_s=1, retries=0), store, clients, org_id=CASE["org_id"])
    assert wf["status"] == "COMPLETED" and calls[1].endswith(":r2")


# ------------------------------------------------------------ C. a store refusal is recorded, never a crash
class Reuse(Fake):
    """A buggy agent that reuses an id already taken by another record (different content)."""

    def __init__(self, record_id):
        super().__init__("PASS")
        self.record_id = record_id

    def run(self, request, timeout_s):
        from shared.utils.hashing import seal
        out = super().run(request, timeout_s)
        ev = seal({**out["evidence"], "record_id": self.record_id})
        return {**out, "evidence": ev}


def test_record_id_collision_is_recorded_as_invalid_output_not_a_crash():
    store = MemoryStore()
    first = run_workflow(CASE, STANDARD, store)
    rid = first["stage_results"][0]["record_id"]
    case2 = {**CASE, "unit_id": "UNIT-0002", "returned": False}
    wf = run_workflow(case2, STANDARD, store, {"prep": Reuse(rid)})
    sr = next(s for s in wf["stage_results"] if s["stage"] == "prep")
    assert sr["state"] == "error" and sr["error"]["code"] == "invalid_output"
    assert wf["status"] == "FAILED" and verify(store.get_evidence(rid, CASE["org_id"]))


def test_unsafe_record_id_on_file_storage_is_recorded_not_a_crash(tmp_path):
    wf = run_workflow(CASE, STANDARD, FileStore(tmp_path), {"prep": Reuse("../../escape")})
    sr = next(s for s in wf["stage_results"] if s["stage"] == "prep")
    assert sr["state"] == "error" and sr["error"]["code"] == "invalid_output"
    assert not (tmp_path.parent / "escape.json").exists()


# ------------------------------------------------------------ D. sys.exit in an agent
def test_agent_calling_sys_exit_is_an_agent_exception():
    def quitter(request):
        sys.exit(3)

    wf = run_workflow(CASE, STANDARD, MemoryStore(), {"prep": inproc(quitter)})
    sr = next(s for s in wf["stage_results"] if s["stage"] == "prep")
    assert sr["error"]["code"] == "agent_exception" and wf["status"] == "FAILED"


# ------------------------------------------------------------ E. API: ambiguous ids
@pytest.fixture
def api(tmp_path, monkeypatch):
    import orchestration.api as api_mod
    monkeypatch.setattr(api_mod, "STORE", FileStore(tmp_path))
    return TestClient(api_mod.app)


def test_workflow_ids_cannot_collide_across_orgs():
    a = workflow_id_for({"org_id": "org_x", "unit_id": "UNIT-1"})
    b = workflow_id_for({"org_id": "org_x-UNIT", "unit_id": "1"})
    assert a == b, "the id format alone is ambiguous, so the API must refuse '-' in org ids"


@pytest.mark.parametrize("body", [
    {"org_id": "org_demo_alpha-UNIT", "unit_id": "0001"},
    {"org_id": "../etc", "unit_id": "UNIT-0001"},
    {"org_id": "org_demo_alpha", "unit_id": "../UNIT-0001"},
])
def test_api_refuses_ambiguous_or_path_like_ids(api, body):
    r = api.post("/workflows", json=body)
    assert r.status_code == 422, r.text


def test_api_create_still_works_for_normal_ids(api):
    r = api.post("/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0001"})
    assert r.status_code == 200 and r.json()["org_id"] == "org_demo_alpha"
