"""Test Prep agent handling and Recovery behavior on real and missing Prep.

Enforces Step 2 and Step 6 requirements:
- Prep is configured as a real agent in agent.json and produces valid evidence.
- Missing or errored Prep never produces a claim by itself in Recovery.
- Inbound-defect and prep-fee charges with no valid completed Prep evidence remain SILENT.
- Real completed Prep evidence contradicting a charge produces a claim in Recovery.
"""
import pytest
from orchestration.clients import AgentTimeout, client_for, load_manifest, InProcClient
from orchestration.orchestrator import load_flow, run_workflow
from orchestration.store import MemoryStore
from tests.helpers import Boom, Fake


def test_prep_is_configured_as_real_agent():
    manifest = load_manifest("prep")
    assert manifest["implementation"] == "real"
    assert manifest["owner"] == "@jpatty-vin"
    assert manifest["mode"] == "inproc"
    assert "stub" not in manifest["agent_id"]

    client = client_for("prep")
    req = {
        "schema_version": "1.0",
        "request_id": "WF-test:prep",
        "workflow_id": "WF-org_demo_alpha-UNIT-0014",
        "stage": "prep",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-0014", "route": "fba"},
        "inputs": [],
        "previous_evidence": [],
        "context": {"overrides": [], "case": {}},
    }
    out = client.run(req, 30)
    ev = out["evidence"]
    assert ev["stage"] == "prep"
    assert ev["agent_id"] == manifest["agent_id"]
    assert ev["decision"]["verdict"] in ("PASS", "FAIL", "UNCERTAIN")
    assert ev["model"]["name"] != "csv-replay-stub"
    assert not ev["payload"].get("stub")


def test_prep_refuses_cross_tenant_request():
    client = client_for("prep")
    req = {
        "schema_version": "1.0",
        "request_id": "WF-test:prep-tenant",
        "workflow_id": "WF-org_demo_bravo-UNIT-0014",
        "stage": "prep",
        # UNIT-0014 belongs to org_demo_alpha, not org_demo_bravo
        "subject": {"org_id": "org_demo_bravo", "subject_id": "UNIT-0014", "route": "fba"},
        "inputs": [],
        "previous_evidence": [],
        "context": {"overrides": [], "case": {}},
    }
    with pytest.raises(Exception):
        client.run(req, 30)


def test_missing_prep_leaves_inbound_defect_fee_silent():
    """When Prep is absent from the flow, Recovery must treat inbound_defect_fee as SILENT."""
    specialist_flow = {
        "flow_id": "test-no-prep",
        "steps": [{"stage": "receiving"}, {"stage": "recovery"}],
        "defaults": {"timeout_s": 10, "retries": 0, "on_uncertain": "continue", "on_error": "continue"},
    }
    case = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": False}
    store = MemoryStore()
    wf = run_workflow(case, specialist_flow, store)

    assert "prep" not in [s["stage"] for s in wf["stage_results"]]
    rcy_record_id = next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "recovery")
    rcy = store.get_evidence(rcy_record_id, case["org_id"])

    inbound_charges = [c for c in rcy["payload"]["charges"] if c["charge_type"] in ("inbound_defect_fee", "prep_fee")]
    assert inbound_charges, "UNIT-0014 has an inbound_defect_fee charge"
    for charge in inbound_charges:
        assert charge["position"] == "SILENT"
        assert charge["evidence_record_ids"] == []

    # Recovery produces no claim, so final outcome must NOT be CLAIM_RECOMMENDED
    assert wf["final_outcome"]["outcome"] != "CLAIM_RECOMMENDED"
    assert wf["final_outcome"]["claimable_usd"] is None


def test_failed_prep_leaves_inbound_defect_fee_silent_and_workflow_incomplete():
    """When Prep fails/errors, Recovery must not claim the inbound defect fee."""
    flow = load_flow()
    case = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": False}
    store = MemoryStore()

    # Prep fails with timeout
    failing_prep = Boom(AgentTimeout("prep timed out"))
    wf = run_workflow(case, flow, store, {"prep": failing_prep})

    assert wf["status"] == "FAILED"
    rcy_record_id = next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "recovery")
    rcy = store.get_evidence(rcy_record_id, case["org_id"])

    inbound_charges = [c for c in rcy["payload"]["charges"] if c["charge_type"] in ("inbound_defect_fee", "prep_fee")]
    for charge in inbound_charges:
        assert charge["position"] == "SILENT"

    assert wf["final_outcome"]["outcome"] == "INCOMPLETE"
    assert wf["final_outcome"]["claimable_usd"] is None


def test_real_prep_compliant_evidence_refutes_charge_in_recovery():
    """When real Prep finds unit compliant, Recovery refutes inbound_defect_fee and recommends a claim."""
    flow = load_flow()
    case = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": False}
    store = MemoryStore()
    wf = run_workflow(case, flow, store)

    assert wf["status"] == "COMPLETED"
    assert wf["final_outcome"]["outcome"] == "CLAIM_RECOMMENDED"
    assert wf["final_outcome"]["claimable_usd"] == 2.0

    rcy_record_id = next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "recovery")
    rcy = store.get_evidence(rcy_record_id, case["org_id"])
    inbound_fee = next(c for c in rcy["payload"]["charges"] if c["charge_type"] == "inbound_defect_fee")
    assert inbound_fee["position"] == "CONTRADICTS"
    assert len(inbound_fee["evidence_record_ids"]) == 1
