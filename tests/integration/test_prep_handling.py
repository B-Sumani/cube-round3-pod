"""Test Prep stub handling and Recovery behavior on missing/stubbed Prep.

Enforces Step 2 requirements:
- Prep is clearly labelled as a stub in agent.json and evidence output.
- Missing or errored Prep never produces a claim by itself in Recovery.
- Inbound-defect and prep-fee charges with no valid completed Prep evidence remain SILENT.
"""
import pytest
from orchestration.clients import AgentTimeout, client_for, load_manifest, InProcClient
from orchestration.orchestrator import load_flow, run_workflow
from orchestration.store import MemoryStore
from tests.helpers import Boom, Fake


def test_prep_is_explicitly_labelled_as_stub():
    manifest = load_manifest("prep")
    assert manifest["implementation"] == "organiser-stub"
    assert "stub" in manifest["agent_id"]
    assert "stub" in manifest["notes"].lower()

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
    assert ev["payload"].get("stub") is True
    assert ev["payload"].get("implementation") == "organiser-stub"
    assert any("[STUB" in c.get("detail", "") for c in ev["checks"])


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
