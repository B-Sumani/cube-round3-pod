"""Cross-agent coordination: what each agent is actually handed, in-process timeouts, and honest stub labels.

Runs the five agents configured in agents/*/agent.json (real or stub) behind a recorder, so these tests keep
holding as each member replaces a stub.
"""
import json
import time
from pathlib import Path

import pytest

from orchestration.clients import InProcClient, client_for, load_manifest
from orchestration.orchestrator import apply_override, flow_stages, load_flow, resume, run_workflow
from orchestration.store import MemoryStore
from tests.helpers import Fake

ROOT = Path(__file__).resolve().parents[2]
STAGES = ("receiving", "prep", "pack", "returns", "recovery")
STANDARD = load_flow(ROOT / "orchestration/flow.json")


class Recorder:
    """Passes every request to the configured agent and keeps a copy of what it was sent."""

    def __init__(self, stage, inner=None):
        self.inner, self.requests = inner or client_for(stage), []

    def run(self, request, timeout_s):
        self.requests.append(json.loads(json.dumps(request)))
        return self.inner.run(request, timeout_s)


def recorders(**inner):
    return {s: Recorder(s, inner.get(s)) for s in STAGES}


# ------------------------------------------------------------ what each agent receives
@pytest.mark.parametrize("case", [
    {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True},
    {"org_id": "org_demo_bravo", "unit_id": "UNIT-0009", "route": "mfn", "returned": True},
], ids=["fba-returned-alpha", "mfn-returned-bravo"])
def test_every_agent_gets_its_org_its_workflow_and_all_earlier_evidence_in_order(case):
    rec = recorders()
    wf = run_workflow(case, STANDARD, MemoryStore(), rec)
    ran = [sr for sr in wf["stage_results"] if sr["state"] != "skipped"]
    assert [sr["stage"] for sr in ran] == [s for s in flow_stages(STANDARD) if rec[s].requests]
    for i, sr in enumerate(ran):
        [req] = rec[sr["stage"]].requests
        assert req["stage"] == sr["stage"] and req["workflow_id"] == wf["workflow_id"]
        assert req["subject"] == {"org_id": case["org_id"], "subject_id": case["unit_id"], "route": case["route"]}
        assert req["context"]["case"]["returned"] is case["returned"]
        assert [r["record_id"] for r in req["previous_evidence"]] == [s["record_id"] for s in ran[:i]], \
            "every earlier record, in stage order, nothing from skipped stages"
        assert {r["subject"]["org_id"] for r in req["previous_evidence"]} <= {case["org_id"]}, "no other tenant's evidence"


def test_skipped_stages_are_never_called():
    rec = recorders()
    run_workflow({"org_id": "org_demo_alpha", "unit_id": "UNIT-0001", "route": "unknown", "returned": False},
                 STANDARD, MemoryStore(), rec)
    assert not rec["prep"].requests and not rec["pack"].requests and not rec["returns"].requests
    assert rec["receiving"].requests and rec["recovery"].requests


def test_downstream_agents_receive_the_override_that_unblocked_them():
    flow = {**STANDARD, "defaults": {**STANDARD["defaults"], "on_uncertain": "block"}}
    case = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True}
    store, rec = MemoryStore(), recorders(receiving=Fake("UNCERTAIN"))
    wf = run_workflow(case, flow, store, rec)
    assert wf["status"] == "BLOCKED" and not rec["prep"].requests
    rid = wf["stage_results"][0]["record_id"]
    apply_override(wf["workflow_id"], store, record_id=rid, new_verdict="PASS", actor="op_amira",
                   reason="re-counted on the dock", org_id=case["org_id"])
    resume(wf["workflow_id"], flow, store, rec, org_id=case["org_id"])
    for stage in ("prep", "returns", "recovery"):
        [req] = rec[stage].requests
        [ovr] = req["context"]["overrides"]
        assert ovr["supersedes"]["record_id"] == rid and ovr["new_verdict"] == "PASS" and ovr["actor"] == "op_amira"
        assert req["previous_evidence"][0]["decision"]["verdict"] == "UNCERTAIN", "the original evidence is not rewritten"


# ------------------------------------------------------------ in-process timeouts (D-110)
class Slow:
    """An in-process agent whose first `hang` calls take `seconds`."""

    def __init__(self, seconds, hang=99):
        self.seconds, self.hang, self.calls = seconds, hang, 0

    def __call__(self, request):
        self.calls += 1
        if self.calls <= self.hang:
            time.sleep(self.seconds)
        return Fake("PASS").run(request, 0)


def inproc(handle):
    return InProcClient(handle=handle)


FAST_TIMEOUT = {**STANDARD, "defaults": {**STANDARD["defaults"], "timeout_s": 0.2, "retries": 1}}
CASE = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True}


def test_hung_inprocess_agent_times_out_is_retried_and_never_becomes_success():
    slow = Slow(2.0)
    t0 = time.monotonic()
    wf = run_workflow(CASE, FAST_TIMEOUT, MemoryStore(), {"prep": inproc(slow)})
    assert time.monotonic() - t0 < 1.8, "the orchestrator stopped waiting"
    sr = next(s for s in wf["stage_results"] if s["stage"] == "prep")
    assert sr["attempts"] == 2, "1 try + 1 retry"
    assert slow.calls == 1, "the retry waited on the running execution; it did not start a duplicate (D-112)"
    assert sr["state"] == "error" and sr["error"]["code"] == "agent_timeout"
    assert wf["status"] == "FAILED" and wf["final_outcome"]["outcome"] == "INCOMPLETE"
    assert wf["final_outcome"]["verdict"] != "PASS"


def test_answer_arriving_during_the_retry_window_is_used_once():
    slow = Slow(0.3, hang=1)  # misses the 0.2 s window, answers inside the retry's window
    wf = run_workflow(CASE, FAST_TIMEOUT, MemoryStore(), {"prep": inproc(slow)})
    sr = next(s for s in wf["stage_results"] if s["stage"] == "prep")
    assert sr["state"] == "completed" and sr["attempts"] == 2 and slow.calls == 1
    assert any(t["event"] == "retry" and t["stage"] == "prep" for t in wf["transitions"])


def test_inprocess_tenant_refusal_and_crash_keep_their_meaning():
    def refuse(request):
        raise LookupError("not in this org")

    def crash(request):
        raise ZeroDivisionError("bug")

    wf = run_workflow(CASE, FAST_TIMEOUT, MemoryStore(), {"prep": inproc(refuse), "returns": inproc(crash)})
    codes = {s["stage"]: s["error"]["code"] for s in wf["stage_results"] if s["error"]}
    assert codes == {"prep": "agent_rejected", "returns": "agent_exception"} and wf["status"] == "FAILED"


# ------------------------------------------------------------ honest labels
@pytest.mark.parametrize("stage", STAGES)
def test_stubs_say_they_are_stubs_and_real_agents_have_provenance(stage, cases):
    manifest = load_manifest(stage)
    case = next(c for c in cases if {"prep": c["route"] == "fba", "pack": c["route"] == "mfn",
                                     "returns": c["returned"]}.get(stage, True))
    req = {"schema_version": "1.0", "request_id": f"WF-{case['org_id']}-{case['unit_id']}:{stage}",
           "workflow_id": f"WF-{case['org_id']}-{case['unit_id']}", "stage": stage,
           "subject": {"org_id": case["org_id"], "subject_id": case["unit_id"], "route": case["route"]},
           "inputs": [], "previous_evidence": [], "context": {"overrides": [], "case": case}}
    model = client_for(stage).run(req, 30)["evidence"]["model"]
    if manifest["implementation"] == "organiser-stub":
        assert "stub" in manifest["agent_id"] and model["name"] == "csv-replay-stub"
    else:
        assert (ROOT / "agents" / stage / "PROVENANCE.md").is_file(), "a real agent names its Round 2 source"
        assert "stub" not in manifest["agent_id"] and model["name"] != "csv-replay-stub"
