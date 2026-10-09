"""End-to-end on the Pod's OWN units (data/pod/, UNIT-P001..P010), against hand-written ground truth (labels.json).

These run the real integrated agents (Receiving = Round 2 agent) plus whatever stubs remain, through the orchestrator.
Rebuild the data with:  python scripts/build_pod_data.py
"""
import json
from pathlib import Path

import pytest

from orchestration.orchestrator import apply_override, load_flow, resume, run_workflow
from orchestration.store import MemoryStore
from shared.utils.hashing import verify
from tests.helpers import AgentUnavailable, Boom, Mangle

ROOT = Path(__file__).resolve().parents[2]
POD = ROOT / "data" / "pod"
LABELS = json.loads((POD / "labels.json").read_text(encoding="utf-8"))["units"]
CASES = {c["unit_id"]: c for c in json.loads((POD / "cases.json").read_text(encoding="utf-8"))}
STANDARD = ROOT / "orchestration" / "flow.json"
SPECIALIST = ROOT / "orchestration" / "flow.specialist.json"


@pytest.fixture(autouse=True)
def pod_data(monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(POD))
    monkeypatch.setenv("RECEIVING_VISION", "off")  # recorded mode: deterministic, no network


def flow(path=STANDARD, **defaults):
    f = load_flow(path)
    return {**f, "defaults": {**f["defaults"], **defaults}}


def run(unit, f=None, store=None, clients=None):
    store = store or MemoryStore()
    return run_workflow(CASES[unit], f or flow(), store, clients), store


def receiving_record(wf, store):
    sr = next(s for s in wf["stage_results"] if s["stage"] == "receiving")
    return store.get_evidence(sr["record_id"], wf["org_id"])


@pytest.mark.parametrize("unit", sorted(LABELS))
def test_final_outcome_matches_ground_truth(unit):
    wf, _ = run(unit)
    label = LABELS[unit]
    assert wf["final_outcome"]["outcome"] == label["final_outcome"], label["scenario"]
    if label["claimable_usd"] is not None:
        assert wf["final_outcome"]["claimable_usd"] == pytest.approx(label["claimable_usd"])


@pytest.mark.parametrize("unit", sorted(LABELS))
def test_receiving_checks_match_ground_truth(unit):
    wf, store = run(unit)
    got = {c["check_key"]: c["verdict"] for c in receiving_record(wf, store)["checks"]}
    assert got == LABELS[unit]["receiving_checks"], LABELS[unit]["scenario"]


def test_clean_unit_completes_clean():
    wf, _ = run("UNIT-P001")
    assert (wf["status"], wf["final_outcome"]["outcome"], wf["final_outcome"]["needs_human"]) == ("COMPLETED", "CLEAN", False)


def test_exception_is_exception_not_claim():
    wf, _ = run("UNIT-P004")
    assert wf["final_outcome"]["outcome"] == "EXCEPTION" and wf["final_outcome"]["claimable_usd"] is None


def test_claim_is_backed_by_contradicting_evidence():
    wf, store = run("UNIT-P009")
    fo = wf["final_outcome"]
    assert fo["outcome"] == "CLAIM_RECOMMENDED" and fo["claimable_usd"] > 0
    rcy = store.get_evidence(next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "recovery"), wf["org_id"])
    [charge] = [c for c in rcy["payload"]["charges"] if c["position"] == "CONTRADICTS"]
    prep_id = next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "prep")
    assert charge["charge_type"] == "inbound_defect_fee" and charge["evidence_record_ids"] == [prep_id]


def test_supplier_shortfall_is_not_claimed_from_the_channel():
    wf, store = run("UNIT-P003")
    rcv = receiving_record(wf, store)
    assert rcv["payload"]["shortfall_units"] == 4 and rcv["payload"]["shortfall_side"] == "supplier"
    rcy = store.get_evidence(next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "recovery"), wf["org_id"])
    lost = [c for c in rcy["payload"]["charges"] if c["charge_type"] == "lost_inbound"]
    assert lost and all(c["position"] == "SILENT" for c in lost)
    assert wf["final_outcome"]["outcome"] == "EXCEPTION"


def test_specialist_flow_without_prep_leaves_inbound_defect_fee_silent():
    wf, store = run("UNIT-P009", flow(SPECIALIST))
    assert "prep" not in {s["stage"] for s in wf["stage_results"]}
    rcy = store.get_evidence(next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "recovery"), wf["org_id"])
    assert {c["charge_type"]: c["position"] for c in rcy["payload"]["charges"]} == {"inbound_defect_fee": "SILENT"}
    assert wf["final_outcome"]["outcome"] == LABELS["UNIT-P009"]["final_outcome_specialist"]


def test_round2_rule_po_inconsistent_is_uncertain_not_short():
    """The stub would call 24/30 a FAIL; the PO itself says 2x12=24, so the Round 2 rule refuses to judge."""
    wf, store = run("UNIT-P007")
    [q] = [c for c in receiving_record(wf, store)["checks"] if c["check_key"] == "quantity"]
    assert q["verdict"] == "UNCERTAIN" and "PO_INCONSISTENT" in q["detail"] and q["uncertain_reason"]


def test_uncertain_blocks_then_human_override_resolves_auditably():
    f, store = flow(on_uncertain="block"), MemoryStore()
    wf, _ = run("UNIT-P006", f, store)
    assert wf["status"] == "BLOCKED" and wf["halted"]["stage"] == "receiving"
    # Halted with later stages unrun: INCOMPLETE + needs_human (as examples/uncertain-path/workflow-state.blocked.json).
    assert wf["final_outcome"]["outcome"] == "INCOMPLETE" and wf["final_outcome"]["needs_human"]
    assert wf["final_outcome"]["provisional"]
    assert all(s["state"] == "pending" for s in wf["stage_results"] if s["stage"] != "receiving" and s["state"] != "skipped")
    rec = receiving_record(wf, store)
    original = json.loads(json.dumps(rec))
    assert rec["decision"]["verdict"] == "UNCERTAIN" and rec["decision"]["needs_human"]

    wf = apply_override(wf["workflow_id"], store, record_id=rec["record_id"], new_verdict="PASS", actor="supervisor:op_pod",
                        reason="Label re-read by hand: SKU-POD-PEN black matches PO", org_id=wf["org_id"])
    wf = resume(wf["workflow_id"], f, store, org_id=wf["org_id"])
    assert (wf["status"], wf["final_outcome"]["outcome"]) == ("COMPLETED", "CLEAN")
    [ovr] = wf["overrides"]
    assert ovr["supersedes"]["record_id"] == rec["record_id"] and ovr["original_verdict"] == "UNCERTAIN"
    assert ovr["actor"] and ovr["reason"] and ovr["at"]
    after = store.get_evidence(rec["record_id"], wf["org_id"])
    assert after == original and verify(after), "the original evidence must be untouched"
    assert wf["final_outcome"]["effective_verdicts"]["receiving"] == "PASS"
    events = [t["event"] for t in wf["transitions"]]
    assert events.index("halted") < events.index("override") < events.index("resumed")


@pytest.mark.parametrize("client", [Boom(AgentUnavailable("down")), Boom(RuntimeError("bug")),
                                    Mangle("receiving", "garbage"), Mangle("receiving", "other_tenant"),
                                    Mangle("receiving", "tampered")], ids=["unavailable", "crash", "garbage", "tenant", "tampered"])
def test_injected_receiving_failure_is_recorded_never_clean(client):
    wf, store = run("UNIT-P001", flow(retries=0), clients={"receiving": client})
    sr = next(s for s in wf["stage_results"] if s["stage"] == "receiving")
    assert sr["state"] == "error" and sr["error"]["code"]
    assert wf["status"] == "FAILED" and wf["final_outcome"]["outcome"] in ("INCOMPLETE", "EXCEPTION")
    assert wf["final_outcome"]["outcome"] != "CLEAN" and wf["errors"]
    assert store.get_evidence(sr["record_id"], wf["org_id"])["status"] in ("pending", "error")


def test_failed_workflow_recovers_on_resume_when_agent_is_back():
    store, f = MemoryStore(), flow(retries=0)
    wf, _ = run("UNIT-P001", f, store, {"receiving": Boom(AgentUnavailable("down"))})
    assert wf["status"] == "FAILED"
    wf = resume(wf["workflow_id"], f, store, org_id=wf["org_id"])
    assert (wf["status"], wf["final_outcome"]["outcome"]) == ("COMPLETED", "CLEAN")
    assert len(wf["evidence_references"]) > len({s["stage"] for s in wf["stage_results"] if s["record_id"]}), \
        "the failed attempt's record stays in the evidence trail"


@pytest.mark.parametrize("unit", ["UNIT-P009", "UNIT-P010", "UNIT-P003"])
def test_final_outcome_traces_to_checks_and_hashed_inputs(unit):
    wf, store = run(unit)
    fo = wf["final_outcome"]
    assert fo["decided_by"] == "orchestrator" and fo["contributing_records"]
    for rid in fo["contributing_records"]:
        rec = store.get_evidence(rid, wf["org_id"])
        assert rec and verify(rec) and rec["subject"]["org_id"] == wf["org_id"]
        assert rec["checks"] or rec["stage"] == "recovery"
    rcv = receiving_record(wf, store)
    hashed = [i for i in rcv["inputs"] if i.get("sha256")]
    assert hashed and all(len(i["sha256"]) == 64 for i in hashed)
    assert all(c["evidence_refs"] for c in rcv["checks"])
    downstream = [store.get_evidence(r, wf["org_id"]) for r in fo["contributing_records"] if r != rcv["record_id"]]
    assert all(rcv["record_id"] in r["upstream_refs"] for r in downstream), "downstream stages consumed Receiving evidence"


def test_pod_units_are_tenant_isolated():
    bravo = CASES["UNIT-P004"]
    wf, _ = run_workflow({**bravo, "org_id": "org_demo_alpha"}, flow(retries=0), MemoryStore()), None
    sr = next(s for s in wf["stage_results"] if s["stage"] == "receiving")
    assert sr["error"]["code"] == "agent_rejected" and wf["status"] == "FAILED"
