from __future__ import annotations

import hashlib
import re
from pathlib import Path
import pytest
from fastapi import HTTPException

from agents.pack.app import handle
from agents.pack.engine import AGENT_ID, STAGE, set_test_adapter
from agents.pack.model_adapter import MockVisionAdapter
from agents.pack.parser import ImageQuality, ModelObservation, ObservedItem
from shared.utils.hashing import verify
from shared.utils.schema import errors

PCK_ID_REGEX = re.compile(r"^PCK-[A-Za-z0-9._-]+$")


def _make_valid_pack_input(
    org_id: str = "org_demo_alpha",
    unit_id: str = "UNIT-0008",
    inputs: list | None = None,
    previous_evidence: list | None = None,
    context: dict | None = None,
    request_suffix: str = "",
) -> dict:
    wf = f"WF-{org_id}-{unit_id}"
    req_id = f"{wf}:pack{request_suffix}"
    return {
        "schema_version": "1.0",
        "request_id": req_id,
        "workflow_id": wf,
        "stage": "pack",
        "subject": {"org_id": org_id, "subject_id": unit_id, "route": "mfn"},
        "inputs": inputs or [],
        "previous_evidence": previous_evidence or [],
        "context": context or {},
    }


def test_pack_contract():
    """Verifies that handle(agent_input) produces a fully contract-compliant Agent Output."""
    agent_input = _make_valid_pack_input()
    out = handle(agent_input)
    assert errors("agent-output", out) == []
    ev = out["evidence"]
    assert errors("evidence", ev) == []
    assert verify(ev)
    assert out["stage"] == "pack"
    assert out["agent_id"] == AGENT_ID
    assert PCK_ID_REGEX.match(ev["record_id"])
    assert out["verdict"] == ev["decision"]["verdict"]
    assert out["status"] == ev["status"]
    assert ev["subject"]["org_id"] == "org_demo_alpha"
    assert ev["subject"]["subject_id"] == "UNIT-0008"


def test_pack_pass(tmp_path, monkeypatch):
    """Verifies that when items match the order lines, verdict is PASS with outcome seal."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img_file = tmp_path / "box.jpg"
    img_bytes = b"\xff\xd8fakeboximage"
    img_file.write_bytes(img_bytes)
    sha = hashlib.sha256(img_bytes).hexdigest()

    obs = ModelObservation(
        observed_items=[
            ObservedItem(sku="SKU-BOTTLE-750", count=1, count_confidence=0.98, identity_confidence=0.98)
        ],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)
    set_test_adapter(mock)
    try:
        agent_input = _make_valid_pack_input(
            inputs=[{"kind": "image", "ref": "box.jpg", "sha256": sha}],
            context={"case": {"order_lines": "SKU-BOTTLE-750:1"}},
            request_suffix="-pass",
        )
        out = handle(agent_input)
        assert errors("agent-output", out) == []
        assert out["verdict"] == "PASS"
        assert out["status"] == "completed"
        assert out["evidence"]["decision"]["outcome"] == "seal"
        assert out["next_step_recommendation"]["action"] == "continue"
        assert all(c["verdict"] == "PASS" for c in out["evidence"]["checks"])
    finally:
        set_test_adapter(None)


def test_pack_fail(tmp_path, monkeypatch):
    """Verifies that missing expected items yield verdict FAIL with outcome stop_and_fix."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img_file = tmp_path / "box.jpg"
    img_bytes = b"\xff\xd8fakeboximage"
    img_file.write_bytes(img_bytes)
    sha = hashlib.sha256(img_bytes).hexdigest()

    obs = ModelObservation(
        observed_items=[],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)
    set_test_adapter(mock)
    try:
        agent_input = _make_valid_pack_input(
            inputs=[{"kind": "image", "ref": "box.jpg", "sha256": sha}],
            context={"case": {"order_lines": "SKU-BOTTLE-750:1"}},
            request_suffix="-fail",
        )
        out = handle(agent_input)
        assert errors("agent-output", out) == []
        assert out["verdict"] == "FAIL"
        assert out["status"] == "completed"
        assert out["evidence"]["decision"]["outcome"] == "stop_and_fix"
        assert out["next_step_recommendation"]["action"] == "route_to_recovery"
        assert "MISSING_ITEMS" in out["evidence"]["payload"]["reason_codes"].values()
    finally:
        set_test_adapter(None)


def test_pack_uncertain(tmp_path, monkeypatch):
    """Verifies that poor image quality yields verdict UNCERTAIN with review action."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img_file = tmp_path / "box.jpg"
    img_bytes = b"\xff\xd8fakeboximage"
    img_file.write_bytes(img_bytes)
    sha = hashlib.sha256(img_bytes).hexdigest()

    obs = ModelObservation(
        observed_items=[
            ObservedItem(sku="SKU-BOTTLE-750", count=1, count_confidence=0.98, identity_confidence=0.98)
        ],
        image_quality=ImageQuality(usable=False, issues=["blur"]),
    )
    mock = MockVisionAdapter(mock_observation=obs)
    set_test_adapter(mock)
    try:
        agent_input = _make_valid_pack_input(
            inputs=[{"kind": "image", "ref": "box.jpg", "sha256": sha}],
            context={"case": {"order_lines": "SKU-BOTTLE-750:1"}},
            request_suffix="-uncertain",
        )
        out = handle(agent_input)
        assert errors("agent-output", out) == []
        assert out["verdict"] == "UNCERTAIN"
        assert out["evidence"]["decision"]["verdict"] == "UNCERTAIN"
        assert out["next_step_recommendation"]["action"] == "review"
        for c in out["evidence"]["checks"]:
            if c["verdict"] == "UNCERTAIN":
                assert c.get("uncertain_reason") is not None
    finally:
        set_test_adapter(None)


def test_pack_wrong_tenant():
    """Verifies that requesting a unit under an unauthorized or mismatched org raises LookupError."""
    unknown_org_input = _make_valid_pack_input(org_id="org_unauthorized")
    with pytest.raises(LookupError):
        handle(unknown_org_input)

    cross_tenant_input = _make_valid_pack_input(org_id="org_demo_alpha", unit_id="UNIT-0006")
    with pytest.raises(LookupError):
        handle(cross_tenant_input)


def test_pack_previous_evidence():
    """Verifies that upstream_refs includes only Receiving records and honors context overrides."""
    import json
    from orchestration.clients import client_for
    from shared.utils.records import build_record
    from tests.conftest import applies, make_input

    cases_data = json.loads((Path(__file__).resolve().parents[3] / "data/sample/cases.json").read_text())
    case = next(c for c in cases_data if applies("pack", c))
    rcv_ev = client_for("receiving").run(make_input("receiving", case), 30)["evidence"]

    prep_input = make_input("prep", case, [rcv_ev])
    prep_ev = build_record(
        prep_input,
        agent_id="prep-stub@0",
        record_id=f"PRP-{case['unit_id']}",
        captured_at=rcv_ev["captured_at"],
        checks=[],
        outcome="compliant",
        reason="prep complete",
        model={"name": "none", "version": "0", "calls": 0},
        verdict="PASS",
    )

    overrides = [
        {
            "override_id": "OVR-01",
            "supersedes": {"record_id": rcv_ev["record_id"], "override_id": None},
            "target": "decision",
            "new_verdict": "FAIL",
            "actor": "operator",
            "at": "2026-06-25T12:00:00Z",
            "reason": "manual inspection",
            "original_verdict": "PASS",
            "previous_verdict": "PASS",
        }
    ]

    pack_input = make_input("pack", case, previous=[rcv_ev, prep_ev], overrides=overrides)
    out = handle(pack_input)
    assert errors("agent-output", out) == []
    ev = out["evidence"]
    assert ev["upstream_refs"] == [rcv_ev["record_id"]]
    assert ev["payload"]["upstream_verdicts"][rcv_ev["record_id"]] == "FAIL"


def test_pack_hash():
    """Verifies deterministic record_id and verified content_hash across identical calls."""
    agent_input = _make_valid_pack_input(request_suffix="-hash")
    out1 = handle(agent_input)
    out2 = handle(agent_input)
    assert out1["evidence"]["record_id"] == out2["evidence"]["record_id"]
    assert out1["evidence"]["content_hash"] == out2["evidence"]["content_hash"]
    assert verify(out1["evidence"])
    assert verify(out2["evidence"])


def test_pack_model_failure(tmp_path, monkeypatch):
    """Verifies fail-open pending_output (UNCERTAIN, code=model_error) on model/API failure."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    set_test_adapter(None)

    img_file = tmp_path / "box.jpg"
    img_file.write_bytes(b"\xff\xd8fakeboximage")

    agent_input = _make_valid_pack_input(
        inputs=[{"kind": "image", "ref": "box.jpg", "sha256": None}],
        context={"case": {"order_lines": "SKU-BOTTLE-750:1"}},
        request_suffix="-modelfail",
    )
    out = handle(agent_input)
    assert errors("agent-output", out) == []
    assert out["verdict"] == "UNCERTAIN"
    assert out["status"] in ("pending", "error")
    assert out["error"]["code"] == "model_error"


def test_pack_invalid_agent_input_rejected():
    """Verifies that invalid input (wrong stage or missing required fields) is rejected with 422."""
    # Wrong stage
    bad_stage_input = _make_valid_pack_input()
    bad_stage_input["stage"] = "prep"
    with pytest.raises(HTTPException) as exc_stage:
        handle(bad_stage_input)
    assert exc_stage.value.status_code == 422

    # Missing required fields
    incomplete_input = {
        "schema_version": "1.0",
        "stage": "pack",
        "inputs": [],
    }
    with pytest.raises(HTTPException) as exc_missing:
        handle(incomplete_input)
    assert exc_missing.value.status_code == 422

    # Non-dict input
    with pytest.raises(HTTPException) as exc_type:
        handle("not-a-dict")
    assert exc_type.value.status_code == 422


def test_pack_quantities_correct_omitted_when_no_items_present(tmp_path, monkeypatch):
    """Verifies that quantities_correct is omitted per EVIDENCE-CONTRACT.md line 93 when no items are present."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img_file = tmp_path / "box.jpg"
    img_bytes = b"\xff\xd8fakeboximage"
    img_file.write_bytes(img_bytes)
    sha = hashlib.sha256(img_bytes).hexdigest()

    obs = ModelObservation(
        observed_items=[],  # Empty box: 0 expected items present
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)
    set_test_adapter(mock)
    try:
        agent_input = _make_valid_pack_input(
            inputs=[{"kind": "image", "ref": "box.jpg", "sha256": sha}],
            context={"case": {"order_lines": "SKU-BOTTLE-750:1"}},
            request_suffix="-omitted-check",
        )
        out = handle(agent_input)
        assert errors("agent-output", out) == []
        assert out["verdict"] == "FAIL"
        check_keys = {c["check_key"] for c in out["evidence"]["checks"]}
        assert "quantities_correct" not in check_keys
        assert "items_present" in check_keys
        assert check_keys == {"items_present", "no_extra_items"}
    finally:
        set_test_adapter(None)
