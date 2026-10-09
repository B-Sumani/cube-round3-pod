
import json
from pathlib import Path

import pytest

from agents.returns import app as returns_app
from agents.returns.engine import MissingRequiredInputError, analyze_return
from agents.returns.r2_logic.models import ReturnCase
from shared.utils.schema import errors


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "data" / "input" / "UNIT-R3-RET-001" / "returns"


def make_request(inputs=None, subject_id="UNIT-R3-RET-001",
                 org_id="org_demo_alpha"):
    return {
        "schema_version": "1.0",
        "request_id": f"WF-{org_id}-{subject_id}:returns",
        "workflow_id": f"WF-{org_id}-{subject_id}",
        "stage": "returns",
        "subject": {
            "org_id": org_id,
            "subject_id": subject_id,
            "route": "fba",
        },
        "inputs": inputs or [],
        "previous_evidence": [],
        "context": {},
    }


def sample_inputs():
    return [
        {
            "ref": f"{SAMPLE_DIR.name}/return_case.json",
            "kind": "document",
        },
        {
            "ref": f"{SAMPLE_DIR.name}/sealed_complete.jpg",
            "kind": "image",
        },
    ]


def test_missing_case_document_returns_pending(monkeypatch, tmp_path):
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    request = make_request(
        inputs=[
            {
                "ref": "UNIT-R3-RET-001/returns/sealed_complete.jpg",
                "kind": "image",
            }
        ]
    )

    output = returns_app.handle(request)

    assert output["status"] == "pending"
    assert output["error"]["code"] == "missing_required_input"
    assert output["error"]["retryable"] is True
    assert output["verdict"] == "UNCERTAIN"


def test_case_from_another_organisation_is_rejected(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    case_dir = tmp_path / "UNIT-R3-RET-001" / "returns"
    case_dir.mkdir(parents=True)
    case_data = json.loads(
        (SAMPLE_DIR / "return_case.json").read_text(encoding="utf-8")
    )
    case_data["org_id"] = "org_demo_bravo"
    (case_dir / "return_case.json").write_text(
        json.dumps(case_data), encoding="utf-8"
    )
    (case_dir / "sealed_complete.jpg").write_bytes(
        (SAMPLE_DIR / "sealed_complete.jpg").read_bytes()
    )

    request = make_request(
        inputs=[
            {
                "ref": "UNIT-R3-RET-001/returns/return_case.json",
                "kind": "document",
            },
            {
                "ref": "UNIT-R3-RET-001/returns/sealed_complete.jpg",
                "kind": "image",
            },
        ]
    )

    with pytest.raises(LookupError, match="another organisation"):
        returns_app.handle(request)


def test_missing_images_raise_required_input_error():
    case = ReturnCase(
        record_id="RTN-TEST",
        unit_id="UNIT-TEST",
        org_id="org_demo_alpha",
        photo_refs=[],
        captured_at="2026-10-08T12:00:00Z",
    )

    with pytest.raises(MissingRequiredInputError):
        analyze_return(case)


def test_valid_sample_produces_contract_valid_output(monkeypatch):
    monkeypatch.setenv("INPUT_DIR", str(ROOT / "data" / "input"))
    request = make_request(
        inputs=[
            {
                "ref": "UNIT-R3-RET-001/returns/return_case.json",
                "kind": "document",
            },
            {
                "ref": "UNIT-R3-RET-001/returns/sealed_complete.jpg",
                "kind": "image",
            },
        ]
    )

    output = returns_app.handle(request)

    assert errors("agent-output", output) == []
    assert output["stage"] == "returns"
    assert output["status"] == "completed"
    assert output["evidence"]["payload"]["operator_disposition_is_reference"] is True
    assert output["evidence"]["payload"]["recommended_disposition"]
    for check in output["evidence"]["checks"]:
        if check["verdict"] == "UNCERTAIN":
            assert check["uncertain_reason"]

def test_case_from_another_subject_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    case_dir = tmp_path / "UNIT-R3-RET-001" / "returns"
    case_dir.mkdir(parents=True)

    case_data = json.loads(
        (SAMPLE_DIR / "return_case.json").read_text(encoding="utf-8")
    )
    case_data["subject_id"] = "UNIT-OTHER"
    (case_dir / "return_case.json").write_text(
        json.dumps(case_data), encoding="utf-8"
    )
    (case_dir / "sealed_complete.jpg").write_bytes(
        (SAMPLE_DIR / "sealed_complete.jpg").read_bytes()
    )

    request = make_request(inputs=[
        {
            "ref": "UNIT-R3-RET-001/returns/return_case.json",
            "kind": "document",
        },
        {
            "ref": "UNIT-R3-RET-001/returns/sealed_complete.jpg",
            "kind": "image",
        },
    ])

    with pytest.raises(LookupError, match="another subject"):
        returns_app.handle(request)


def test_path_traversal_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="escapes INPUT_DIR"):
        returns_app.resolve_input_ref("../outside.json")

def test_uncertain_identity_fixture_preserves_uncertainty():
    from agents.returns.engine import analyze_return
    from agents.returns.r2_logic.models import ReturnCase

    case = ReturnCase(
        record_id="RTN-UNCERTAIN-TEST",
        unit_id="UNIT-R3-RET-001",
        org_id="org_demo_alpha",
        photo_refs=[
            str(SAMPLE_DIR / "uncertain_identity.jpg"),
        ],
        captured_at="2026-10-08T12:00:00Z",
    )

    result = analyze_return(case)

    identity_check = next(
        check for check in result["checks"]
        if check.check_key == "identity_match"
    )

    assert identity_check.verdict == "UNCERTAIN"