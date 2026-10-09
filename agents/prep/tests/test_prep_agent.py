import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from agents.prep.app import app

client = TestClient(app)

@pytest.fixture
def base_request():
    return {
        "schema_version": "1.0",
        "request_id": "test_req_001",
        "workflow_id": "wf_12345",
        "stage": "prep",
        "subject": {
            "org_id": "org_acme",
            "subject_id": "UNIT-001",
            "route": "fba"
        },
        "inputs": [
            {"ref": "eval/photos/unit_001.jpg", "kind": "image", "sha256": None}
        ],
        "previous_evidence": [],
        "context": {"packaging": "polybag"}
    }

def test_prep_contract(base_request):
    """Test 1: Output contract matches schema requirements."""
    with patch("agents.prep.engine.call_gemini_vision") as mock_vision:
        mock_vision.return_value = (
            [{"check_key": "polybag_sealed", "verdict": "PASS", "confidence": 0.98}],
            "gemini-2.5-flash",
            120.0,
            0.50,
            None
        )
        response = client.post("/run", json=base_request)
        assert response.status_code == 200
        output = response.json()
        assert output["schema_version"] == "1.0"
        assert output["stage"] == "prep"
        assert output["verdict"] == "PASS"

def test_prep_pass(base_request):
    """Test 2: All passing checks yield PASS verdict."""
    with patch("agents.prep.engine.call_gemini_vision") as mock_vision:
        mock_vision.return_value = (
            [
                {"check_key": "polybag_sealed", "verdict": "PASS", "confidence": 0.99},
                {"check_key": "suffocation_warning", "verdict": "PASS", "confidence": 0.95}
            ],
            "gemini-2.5-flash",
            150.0,
            0.50,
            None
        )
        response = client.post("/run", json=base_request)
        assert response.status_code == 200
        output = response.json()
        assert output["verdict"] == "PASS"
        assert output["status"] == "completed"

def test_prep_uncertain(base_request):
    """Test 3: UNCERTAIN check yields UNCERTAIN verdict and pending status."""
    with patch("agents.prep.engine.call_gemini_vision") as mock_vision:
        mock_vision.return_value = (
            [
                {"check_key": "polybag_sealed", "verdict": "PASS", "confidence": 0.99},
                {"check_key": "suffocation_warning", "verdict": "UNCERTAIN", "confidence": 0.40, "uncertain_reason": "poor_image"}
            ],
            "gemini-2.5-flash",
            180.0,
            0.50,
            None
        )
        response = client.post("/run", json=base_request)
        assert response.status_code == 200
        output = response.json()
        assert output["verdict"] == "UNCERTAIN"
        assert output["status"] == "pending"

def test_prep_wrong_tenant(base_request):
    """Test 4: Cross-tenant evidence returns HTTP 404."""
    base_request["previous_evidence"] = [
        {
            "schema_version": "1.0",
            "record_id": "RCV-001",
            "workflow_id": "wf_12345",
            "stage": "receiving",
            "agent_id": "rcv@1.0.0",
            "subject": {"org_id": "org_OTHER", "subject_id": "UNIT-001"},
            "status": "completed",
            "captured_at": "2026-10-01T00:00:00Z",
            "produced_at": "2026-10-01T00:00:00Z",
            "model": {"name": "test", "version": "1.0"},
            "checks": [],
            "decision": {"verdict": "PASS", "outcome": "ok", "reason": "ok"},
            "upstream_refs": [],
            "content_hash": "a"*64
        }
    ]
    response = client.post("/run", json=base_request)
    assert response.status_code == 404

def test_prep_invalid_stage(base_request):
    """Test 5: Invalid stage returns HTTP 422."""
    base_request["stage"] = "receiving"
    response = client.post("/run", json=base_request)
    assert response.status_code == 422

def test_prep_model_failure_fail_open(base_request):
    """Test 6: Model failure returns HTTP 200 with UNCERTAIN status and error object."""
    err_payload = {"code": "model_error", "message": "Model API timeout", "retryable": True}
    with patch("agents.prep.engine.call_gemini_vision") as mock_vision:
        mock_vision.return_value = (
            [{"check_key": "polybag_sealed", "verdict": "UNCERTAIN", "uncertain_reason": "model_error"}],
            "gemini-2.5-flash",
            0.0,
            0.50,
            err_payload
        )
        response = client.post("/run", json=base_request)
        assert response.status_code == 200
        output = response.json()
        assert output["verdict"] == "UNCERTAIN"
        assert output["status"] == "pending"
        assert output["error"]["code"] == "model_error"

def test_prep_evidence_hash_and_refs(base_request):
    """Test 7: Content hash and upstream references are populated properly."""
    base_request["previous_evidence"] = [
        {
            "schema_version": "1.0",
            "record_id": "RCV-100200",
            "workflow_id": "wf_12345",
            "stage": "receiving",
            "agent_id": "rcv@1.0.0",
            "subject": {"org_id": "org_acme", "subject_id": "UNIT-001"},
            "status": "completed",
            "captured_at": "2026-10-01T00:00:00Z",
            "produced_at": "2026-10-01T00:00:00Z",
            "model": {"name": "test", "version": "1.0"},
            "checks": [],
            "decision": {"verdict": "PASS", "outcome": "ok", "reason": "ok"},
            "upstream_refs": [],
            "content_hash": "b"*64
        }
    ]
    with patch("agents.prep.engine.call_gemini_vision") as mock_vision:
        mock_vision.return_value = (
            [{"check_key": "polybag_sealed", "verdict": "PASS", "confidence": 0.95}],
            "gemini-2.5-flash",
            100.0,
            0.50,
            None
        )
        response = client.post("/run", json=base_request)
        assert response.status_code == 200
        output = response.json()
        assert len(output["evidence"]["content_hash"]) == 64
        assert "RCV-100200" in output["evidence"]["upstream_refs"]