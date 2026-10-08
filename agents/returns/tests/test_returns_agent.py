from __future__ import annotations

from pathlib import Path

import pytest

from agents.returns.app import handle
from shared.utils.hashing import verify
from shared.utils.schema import errors


ROOT = Path("data/input")
CASE_ID = "UNIT-R3-RET-001"


def make_request(
    *,
    request_id: str = "REQ-RET-TEST-001",
    org_id: str = "org_demo_alpha",
    subject_id: str = CASE_ID,
    previous_evidence: list[dict] | None = None,
    inputs: list[dict] | None = None,
) -> dict:
    if inputs is None:
        inputs = [
            {
                "ref": f"{CASE_ID}/returns/return_case.json",
                "kind": "document",
                "sha256": None,
            },
            {
                "ref": f"{CASE_ID}/returns/sealed_complete.jpg",
                "kind": "image",
                "sha256": None,
            },
        ]

    return {
        "schema_version": "1.0",
        "request_id": request_id,
        "workflow_id": f"WF-{org_id}-{subject_id}",
        "stage": "returns",
        "subject": {
            "org_id": org_id,
            "subject_id": subject_id,
            "route": "fba",
        },
        "inputs": inputs,
        "previous_evidence": previous_evidence or [],
        "context": {
            "overrides": [],
        },
    }


def test_returns_output_is_contract_valid():
    output = handle(make_request())

    assert errors("agent-output", output) == []

    evidence = output["evidence"]

    assert output["schema_version"] == "1.0"
    assert output["stage"] == "returns"
    assert output["agent_id"] == "returns-manager@1.0.0"
    assert output["status"] == "completed"
    assert output["workflow_id"] == "WF-org_demo_alpha-UNIT-R3-RET-001"

    assert evidence["record_id"] == "RTN-UNIT-R3-RET-001"
    assert evidence["stage"] == "returns"
    assert evidence["subject"]["org_id"] == "org_demo_alpha"
    assert evidence["subject"]["subject_id"] == CASE_ID

    check_keys = {
        item["check_key"]
        for item in evidence["checks"]
    }

    assert check_keys == {
        "identity_match",
        "completeness",
        "condition",
    }

    assert output["verdict"] == evidence["decision"]["verdict"]
    assert output["status"] == evidence["status"]

    assert verify(evidence)


def test_returns_identity_passes():
    output = handle(make_request())

    checks = {
        item["check_key"]: item
        for item in output["evidence"]["checks"]
    }

    assert checks["identity_match"]["verdict"] == "PASS"


def test_returns_completeness_passes():
    output = handle(make_request())

    checks = {
        item["check_key"]: item
        for item in output["evidence"]["checks"]
    }

    assert checks["completeness"]["verdict"] == "PASS"


def test_returns_condition_passes_when_supplied():
    output = handle(make_request())

    checks = {
        item["check_key"]: item
        for item in output["evidence"]["checks"]
    }

    assert checks["condition"]["verdict"] == "PASS"
def test_returns_uncertain_identity_is_preserved():
    inputs = [
        {
            "ref": f"{CASE_ID}/returns/return_case.json",
            "kind": "document",
            "sha256": None,
        },
        {
            "ref": f"{CASE_ID}/returns/uncertain_identity.jpg",
            "kind": "image",
            "sha256": None,
        },
    ]

    output = handle(
        make_request(
            request_id="REQ-RET-UNCERTAIN-001",
            inputs=inputs,
        )
    )

    checks = {
        item["check_key"]: item
        for item in output["evidence"]["checks"]
    }

    assert checks["identity_match"]["verdict"] == "UNCERTAIN"
    assert output["verdict"] == "UNCERTAIN"
    assert (
        output["evidence"]["decision"]["outcome"]
        == "pending_review"
    )


def test_returns_missing_required_image_is_explicit():
    inputs = [
        {
            "ref": f"{CASE_ID}/returns/return_case.json",
            "kind": "document",
            "sha256": None,
        }
    ]

    output = handle(
        make_request(
            request_id="REQ-RET-MISSING-001",
            inputs=inputs,
        )
    )

    assert output["status"] == "pending"
    assert output["verdict"] == "UNCERTAIN"
    assert (
        output["evidence"]["decision"]["outcome"]
        == "pending_review"
    )

    error = output["evidence"]["error"]
    assert error is not None
    assert error["code"] == "missing_required_input"
def test_returns_wrong_tenant_is_rejected():
    request = make_request(
        request_id="REQ-RET-TENANT-001",
        org_id="org_demo_bravo",
    )

    with pytest.raises(LookupError):
        handle(request)
def test_returns_consumes_previous_evidence():
    workflow_id = "WF-org_demo_alpha-UNIT-R3-RET-001"

    previous_evidence = [
        {
            "schema_version": "1.0",
            "record_id": "RCV-UNIT-R3-RET-001",
            "workflow_id": workflow_id,
            "stage": "receiving",
            "agent_id": "receiving-manager@1.0.0",
            "subject": {
                "org_id": "org_demo_alpha",
                "subject_id": CASE_ID,
                "unit_id": CASE_ID,
                "unit_scope": "unit",
                "refs": {
                    "order_id": "ORD-R3-RET-001",
                    "sku": "SKU-TEST-001",
                    "asin": "ASIN-TEST-001"
                }
            },
            "status": "completed",
            "captured_at": "2026-10-08T11:00:00Z",
            "produced_at": "2026-10-08T11:00:01Z",
            "model": {
                "name": "test",
                "version": "1.0",
                "calls": 0
            },
            "inputs": [],
            "checks": [],
            "decision": {
                "verdict": "PASS",
                "outcome": "continue",
                "reason": "Receiving passed",
                "confidence": 1.0,
                "needs_human": False
            },
            "payload": {},
            "upstream_refs": [],
            "overrides": [],
            "error": None,
            "content_hash": "0" * 64
        }
    ]

    output = handle(
        make_request(
            request_id="REQ-RET-UPSTREAM-001",
            previous_evidence=previous_evidence,
        )
    )

    assert output["status"] == "completed"

    assert (
        output["evidence"]["upstream_refs"]
        == ["RCV-UNIT-R3-RET-001"]
    )
def test_returns_operator_disposition_does_not_drive_ai_decision():
    import json

    case_path = (
        Path("data/input")
        / CASE_ID
        / "returns"
        / "return_case.json"
    )

    original = case_path.read_text(
        encoding="utf-8"
    )

    try:
        data = json.loads(original)

        # Change ONLY the operator/reference field.
        data["operator_disposition"] = "dispose"

        case_path.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )

        output = handle(
            make_request(
                request_id="REQ-RET-OPERATOR-001"
            )
        )

        # The AI recommendation must still be based on:
        # identity + completeness + condition.
        assert (
            output["evidence"]["decision"]["outcome"]
            == "restock"
        )

        assert (
            output["evidence"]["payload"][
                "operator_disposition_is_reference"
            ]
            is True
        )

    finally:
        # Restore the original fixture.
        case_path.write_text(
            original,
            encoding="utf-8",
        )
def test_returns_consumes_previous_evidence():
    workflow_id = "WF-org_demo_alpha-UNIT-R3-RET-001"

    previous_evidence = [{
        "schema_version": "1.0",
        "record_id": "RCV-UNIT-R3-RET-001",
        "workflow_id": workflow_id,
        "stage": "receiving",
        "agent_id": "receiving-manager@1.0.0",
        "subject": {
            "org_id": "org_demo_alpha",
            "subject_id": CASE_ID,
            "unit_id": CASE_ID,
            "unit_scope": "unit",
            "refs": {
                "order_id": "ORD-R3-RET-001",
                "sku": "SKU-TEST-001",
                "asin": "ASIN-TEST-001"
            }
        },
        "status": "completed",
        "captured_at": "2026-10-08T11:00:00Z",
        "produced_at": "2026-10-08T11:00:01Z",
        "model": {
            "name": "test",
            "version": "1.0",
            "calls": 0
        },
        "inputs": [],
        "checks": [],
        "decision": {
            "verdict": "PASS",
            "outcome": "continue",
            "reason": "Receiving passed",
            "confidence": 1.0,
            "needs_human": False
        },
        "payload": {},
        "upstream_refs": [],
        "overrides": [],
        "error": None,
        "content_hash": "0" * 64
    }]

    output = handle(
        make_request(
            request_id="REQ-RET-UPSTREAM-001",
            previous_evidence=previous_evidence
        )
    )

    assert output["status"] == "completed"
    assert output["evidence"]["upstream_refs"] == [
        "RCV-UNIT-R3-RET-001"
    ]
def test_returns_operator_disposition_does_not_drive_ai_decision():
    import json

    case_path = (
        Path("data/input")
        / CASE_ID
        / "returns"
        / "return_case.json"
    )

    original = case_path.read_text(encoding="utf-8")

    try:
        data = json.loads(original)
        data["operator_disposition"] = "dispose"

        case_path.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8"
        )

        output = handle(
            make_request(
                request_id="REQ-RET-OPERATOR-001"
            )
        )

        assert output["evidence"]["decision"]["outcome"] == "restock"
        assert (
            output["evidence"]["payload"]["operator_disposition_is_reference"]
            is True
        )

    finally:
        case_path.write_text(
            original,
            encoding="utf-8"
        )
def test_returns_same_request_is_idempotent():
    request = make_request(
        request_id="REQ-RET-IDEMPOTENT-001"
    )

    first = handle(request)
    second = handle(request)

    assert first["status"] == "completed"
    assert second["status"] == "completed"

    assert first["verdict"] == second["verdict"]

    assert (
        first["evidence"]["decision"]["outcome"]
        == second["evidence"]["decision"]["outcome"]
    )

    assert (
        first["evidence"]["decision"]["verdict"]
        == second["evidence"]["decision"]["verdict"]
    )

    assert (
        first["evidence"]["subject"]
        == second["evidence"]["subject"]
    )

    assert (
        first["evidence"]["checks"]
        == second["evidence"]["checks"]
    )
def test_returns_evidence_hash_is_valid():
    output = handle(
        make_request(
            request_id="REQ-RET-HASH-001"
        )
    )

    evidence = output["evidence"]

    assert isinstance(evidence["content_hash"], str)
    assert len(evidence["content_hash"]) == 64

    assert all(
        ch in "0123456789abcdef"
        for ch in evidence["content_hash"].lower()
    )

    assert verify(evidence)
def test_returns_missing_parts_is_not_restock():
    request = make_request(
        request_id="REQ-RET-MISSING-PARTS-002"
    )

    request["workflow_id"] = "WF-org_demo_alpha-UNIT-R3-RET-002"
    request["subject"]["subject_id"] = "UNIT-R3-RET-002"

    request["inputs"] = [
        {
            "kind": "document",
            "ref": "UNIT-R3-RET-002/returns/return_case.json"
        },
        {
            "kind": "image",
            "ref": "UNIT-R3-RET-002/returns/missing_parts.jpg"
        }
    ]

    output = handle(request)

    assert output["status"] == "completed"
    assert output["verdict"] == "FAIL"

    checks = {
        item["check_key"]: item
        for item in output["evidence"]["checks"]
    }

    assert checks["completeness"]["verdict"] == "FAIL"

    assert (
        output["evidence"]["decision"]["outcome"]
        == "refurbish"
    )