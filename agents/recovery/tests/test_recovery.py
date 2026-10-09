"""Unit and contract tests for Recovery Manager agent."""
import pytest
from agents.recovery.app import handle
from shared.utils.schema import errors
from tests.conftest import make_input


def test_recovery_handle_basic_contract(cases):
    """Verify Recovery handle returns valid Agent Output schema."""
    case = next(c for c in cases if c["unit_id"] == "UNIT-0014")
    inp = make_input("recovery", case)
    out = handle(inp)
    assert errors("agent-output", out) == []
    assert out["stage"] == "recovery"
    assert out["evidence"]["record_id"] == "RCY-UNIT-0014"


def test_recovery_contradicts_charge_when_prep_passes(cases):
    """Prep PASS refutes inbound defect fee -> CONTRADICTS (claim recommended)."""
    case = next(c for c in cases if c["unit_id"] == "UNIT-0014")
    prep_evidence = {
        "record_id": "PRP-UNIT-0014",
        "stage": "prep",
        "agent_id": "prep@1.0",
        "status": "completed",
        "decision": {"verdict": "PASS"},
        "checks": [{"check_key": "polybag", "verdict": "PASS"}]
    }
    inp = make_input("recovery", case, previous=[prep_evidence])
    out = handle(inp)
    charges = out["evidence"]["payload"]["charges"]
    inbound_charge = next(c for c in charges if c["charge_type"] == "inbound_defect_fee")
    assert inbound_charge["position"] == "CONTRADICTS"
    assert "PRP-UNIT-0014" in inbound_charge["evidence_record_ids"]


def test_recovery_supports_charge_when_prep_fails(cases):
    """Prep FAIL confirms inbound defect fee -> SUPPORTS (no claim)."""
    case = next(c for c in cases if c["unit_id"] == "UNIT-0014")
    prep_evidence = {
        "record_id": "PRP-UNIT-0014",
        "stage": "prep",
        "agent_id": "prep@1.0",
        "status": "completed",
        "decision": {"verdict": "FAIL"},
        "checks": [{"check_key": "polybag", "verdict": "FAIL"}]
    }
    inp = make_input("recovery", case, previous=[prep_evidence])
    out = handle(inp)
    charges = out["evidence"]["payload"]["charges"]
    inbound_charge = next(c for c in charges if c["charge_type"] == "inbound_defect_fee")
    assert inbound_charge["position"] == "SUPPORTS"


def test_recovery_tenancy_refusal(cases):
    """Recovery must raise LookupError for unknown subject / org."""
    case = next(c for c in cases if c["unit_id"] == "UNIT-0014")
    bad_inp = make_input("recovery", {**case, "org_id": "org_unknown_xyz"})
    with pytest.raises(LookupError):
        handle(bad_inp)
