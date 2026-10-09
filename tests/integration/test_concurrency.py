"""Concurrency regressions (docs/decisions.md D-115, D-116).

Fix 1: two callers advancing the SAME workflow at once (two POST /workflows, a resume racing an override, the CLI
and the API on one out/ directory) must not run a stage twice, crash on a shared temp file, or lose an update.
Fix 2: two writers creating the SAME evidence id at once must not silently overwrite each other.
"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from orchestration.orchestrator import apply_override, load_flow, resume, run_workflow
from orchestration.store import EvidenceConflict, FileStore, MemoryStore, TenantViolation
from shared.utils.hashing import seal, verify
from tests.helpers import Fake

ROOT = Path(__file__).resolve().parents[2]
STANDARD = load_flow(ROOT / "orchestration/flow.json")
CASE = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True}
WF_ID = "WF-org_demo_alpha-UNIT-0014"


@pytest.fixture(params=["memory", "file"])
def store(request, tmp_path):
    return MemoryStore() if request.param == "memory" else FileStore(tmp_path)


class Counting(Fake):
    """A slow PASS agent that counts executions across every client instance sharing `log`."""

    def __init__(self, log, seconds=0.3, verdict="PASS"):
        super().__init__(verdict)
        self.log, self.seconds = log, seconds

    def run(self, request, timeout_s):
        self.log.append(request["request_id"])
        time.sleep(self.seconds)
        return super().run(request, timeout_s)


def in_threads(*fns):
    errors, results = [], []

    def wrap(fn):
        try:
            results.append(fn())
        except Exception as exc:  # collected: a crash in either caller is a failure of the test
            errors.append(exc)

    threads = [threading.Thread(target=wrap, args=(fn,)) for fn in fns]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results, errors


# ------------------------------------------------------------ Fix 1: one workflow, many callers
def test_concurrent_creates_run_each_stage_once_and_do_not_crash(store):
    log = []
    results, errors = in_threads(*[lambda: run_workflow(CASE, STANDARD, store, {"prep": Counting(log)})] * 3)
    assert errors == [], errors
    assert log == [f"{WF_ID}:prep"], f"prep ran {len(log)} times"
    wf = store.load_workflow(WF_ID, CASE["org_id"])
    assert wf["status"] == "COMPLETED" and wf["final_outcome"]["outcome"] in ("CLEAN", "CLAIM_RECOMMENDED")
    assert sum(t["event"] == "stage_completed" and t["stage"] == "prep" for t in wf["transitions"]) == 1
    assert len(wf["evidence_references"]) == len(set(wf["evidence_references"]))


def _blocked(store):
    flow = {**STANDARD, "defaults": {**STANDARD["defaults"], "on_uncertain": "block"}}
    wf = run_workflow(CASE, flow, store, {"receiving": Fake("UNCERTAIN")})
    assert wf["status"] == "BLOCKED"
    return flow, wf["stage_results"][0]["record_id"]


def test_override_during_a_running_resume_is_not_lost(store):
    flow, rid = _blocked(store)
    apply_override(WF_ID, store, record_id=rid, new_verdict="PASS", actor="op_amira", reason="re-counted",
                   org_id=CASE["org_id"])
    log = []

    def late_override():
        time.sleep(0.1)  # lands while the resume is inside the slow Prep stage
        return apply_override(WF_ID, store, record_id=rid, new_verdict="PASS", actor="sup_li",
                              reason="second check", org_id=CASE["org_id"])

    _, errors = in_threads(lambda: resume(WF_ID, flow, store, {"prep": Counting(log, 0.5)}, org_id=CASE["org_id"]),
                           late_override)
    assert errors == [], errors
    wf = store.load_workflow(WF_ID, CASE["org_id"])
    assert [o["actor"] for o in wf["overrides"]] == ["op_amira", "sup_li"], "the second override was lost"
    assert [o["override_id"] for o in wf["overrides"]] == ["OVR-001", "OVR-002"]
    assert wf["status"] == "COMPLETED" and log == [f"{WF_ID}:prep"]


def test_concurrent_resumes_run_the_failed_stage_once(store):
    wf = run_workflow(CASE, STANDARD, store, {"prep": Fake("PASS", status="error")})
    assert wf["status"] == "FAILED"
    log = []
    _, errors = in_threads(*[lambda: resume(WF_ID, STANDARD, store, {"prep": Counting(log)}, org_id=CASE["org_id"])] * 2)
    assert errors == [], errors
    assert log == [f"{WF_ID}:prep:r2"], f"prep re-ran {len(log)} times"
    assert store.load_workflow(WF_ID, CASE["org_id"])["status"] == "COMPLETED"


def test_lock_wait_is_bounded_and_reported(tmp_path, monkeypatch):
    from orchestration import store as store_mod
    monkeypatch.setattr(store_mod, "LOCK_TIMEOUT_S", 0.2)
    fs = FileStore(tmp_path)
    with fs.workflow_lock(WF_ID):
        _, errors = in_threads(lambda: run_workflow(CASE, STANDARD, fs))
    assert len(errors) == 1 and isinstance(errors[0], store_mod.WorkflowBusy)


def test_lock_does_not_cross_workflows(store):
    """A different workflow never waits on this one's lock."""
    other = {**CASE, "unit_id": "UNIT-0002", "returned": False}
    with store.workflow_lock(WF_ID):
        _, errors = in_threads(lambda: run_workflow(other, STANDARD, store))
    assert errors == []


CHILD = """
import sys, time
sys.path.insert(0, {root!r})
from orchestration.orchestrator import load_flow, run_workflow
from orchestration.store import FileStore
from tests.helpers import Fake
class Slow(Fake):
    def run(self, request, timeout_s):
        with open({log!r}, "a") as fh:
            fh.write(request["request_id"] + "\\n")
        time.sleep(0.5)
        return super().run(request, timeout_s)
run_workflow({case!r}, load_flow({flow!r}), FileStore({out!r}), {{"prep": Slow("PASS")}})
"""


def test_two_processes_on_one_out_dir_run_each_stage_once(tmp_path):
    """The CLI and the API are separate processes sharing out/: the lock must hold across processes."""
    log = tmp_path / "executions.log"
    code = CHILD.format(root=str(ROOT), log=str(log), case=CASE, flow=str(ROOT / "orchestration/flow.json"),
                        out=str(tmp_path / "out"))
    procs = [subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    errs = [p.communicate(timeout=60)[1] for p in procs]
    assert [p.returncode for p in procs] == [0, 0], errs
    assert log.read_text().split() == [f"{WF_ID}:prep"]
    wf = json.loads((tmp_path / "out" / "workflows" / f"{WF_ID}.json").read_text())
    assert wf["status"] == "COMPLETED"


def test_api_answers_409_while_another_caller_holds_the_workflow(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import orchestration.api as api_mod
    from orchestration import store as store_mod
    monkeypatch.setattr(store_mod, "LOCK_TIMEOUT_S", 0.2)
    fs = FileStore(tmp_path)
    monkeypatch.setattr(api_mod, "STORE", fs)
    client = TestClient(api_mod.app)
    assert client.post("/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0014"}).status_code == 200
    with fs.workflow_lock(WF_ID):
        busy = in_threads(lambda: client.post("/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0014"}),
                          lambda: client.post(f"/workflows/{WF_ID}/resume", headers={"X-Org-Id": "org_demo_alpha"}))[0]
    assert sorted(r.status_code for r in busy) == [409, 409]


# ------------------------------------------------------------ Fix 2: atomic evidence creation
def _record(v, org="org_demo_alpha", rid="RCV-RACE-1"):
    return seal({"record_id": rid, "subject": {"org_id": org, "subject_id": "UNIT-0014"}, "decision": {"verdict": v}})


def race_put(store, records, org_of=lambda r: r["subject"]["org_id"]):
    """Both writers pass the 'does it exist?' check before either writes: the window a check-then-write store has."""
    barrier, seen = threading.Barrier(len(records)), threading.local()
    original = store._read_evidence

    def read_once_in_lockstep(record_id):
        result = original(record_id)
        if not getattr(seen, "done", False):
            seen.done = True
            barrier.wait(5)
        return result

    store._read_evidence = read_once_in_lockstep
    outcome = {}

    def put(r):
        try:
            store.put_evidence(r, org_of(r))
            outcome[r["decision"]["verdict"]] = "stored"
        except Exception as exc:
            outcome[r["decision"]["verdict"]] = type(exc).__name__

    threads = [threading.Thread(target=put, args=(r,)) for r in records]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    store._read_evidence = original
    return outcome


def test_racing_writers_of_one_evidence_id_never_overwrite(store):
    a, b = _record("PASS"), _record("FAIL")
    outcome = race_put(store, [a, b])
    assert sorted(outcome.values()) == ["EvidenceConflict", "stored"], outcome
    winner = a if outcome["PASS"] == "stored" else b
    kept = store.get_evidence("RCV-RACE-1", "org_demo_alpha")
    assert kept == winner and verify(kept), "the first record survives untouched"


def test_racing_identical_writes_are_idempotent(store):
    outcome = race_put(store, [_record("PASS"), _record("PASS")])
    assert list(outcome.values()) == ["stored"] and verify(store.get_evidence("RCV-RACE-1", "org_demo_alpha"))


def test_racing_writers_from_two_orgs_cannot_take_over_an_id(store):
    outcome = race_put(store, [_record("PASS", "org_demo_alpha"), _record("FAIL", "org_demo_bravo")])
    assert sorted(outcome.values()) == ["TenantViolation", "stored"], outcome
    owner = "org_demo_alpha" if outcome["PASS"] == "stored" else "org_demo_bravo"
    assert store.get_evidence("RCV-RACE-1", owner)["subject"]["org_id"] == owner


def test_existing_record_is_kept_when_a_later_write_conflicts(store):
    store.put_evidence(_record("PASS"), "org_demo_alpha")
    with pytest.raises(EvidenceConflict):
        store.put_evidence(_record("FAIL"), "org_demo_alpha")
    assert store.get_evidence("RCV-RACE-1", "org_demo_alpha")["decision"]["verdict"] == "PASS"


def test_file_evidence_writes_leave_no_partial_or_temp_files(tmp_path):
    fs = FileStore(tmp_path)
    fs.put_evidence(_record("PASS"), "org_demo_alpha")
    assert sorted(p.name for p in (tmp_path / "evidence").iterdir()) == ["RCV-RACE-1.json"]
