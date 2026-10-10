"""Tests verifying image upload endpoint POST /api/stages/{stage}/run-upload."""
import hashlib
import json
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

import orchestration.api as api_mod
from orchestration.store import FileStore
from agents.pack.engine import set_test_adapter
from agents.pack.model_adapter import VisionModelAdapter
from agents.pack.parser import ModelObservation, ObservedItem, ImageQuality


class FakeVisionAdapter(VisionModelAdapter):
    def analyze_box(self, images=None, candidate_skus=None, catalogue=None, timeout_seconds=None, **kwargs):
        obs = ModelObservation(
            observed_items=[ObservedItem(sku="SKU-BEV-001", count=1, count_confidence=0.99, identity_confidence=0.99)],
            image_quality=ImageQuality(usable=True),
            occlusion_suspected=False,
        )
        return obs, 42, {"name": "fake-vision", "version": "1.0", "calls": 1}


@pytest.fixture(autouse=True)
def cleanup_adapter():
    yield
    set_test_adapter(None)


def test_upload_valid_image(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "STORE", FileStore(tmp_path / "store"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    set_test_adapter(FakeVisionAdapter())

    client = TestClient(api_mod.app)
    fake_img = b"\xff\xd8\xff\xe0" + b"TEST_IMAGE_BYTES" * 10 + b"\xff\xd9"
    expected_sha = hashlib.sha256(fake_img).hexdigest()

    resp = client.post(
        "/api/stages/pack/run-upload",
        files={"file": ("box.jpg", fake_img, "image/jpeg")},
        data={"unit_id": "UNIT-0010", "order_lines": "SKU-BEV-001:1"},
        headers={"X-Org-Id": "org_demo_alpha"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["is_ad_hoc_upload"] is True
    assert "storage_note" in data
    assert "ephemeral" in data["storage_note"]

    # Verify Evidence Record
    ev = data["evidence"]
    assert ev["schema_version"] == "1.0"
    assert ev["stage"] == "pack"
    assert ev["subject"]["subject_id"] == "UNIT-0010"
    assert ev["subject"]["org_id"] == "org_demo_alpha"
    assert ev["decision"]["verdict"] == "PASS"

    # Inputs verification
    inputs = ev["inputs"]
    assert len(inputs) == 1
    assert inputs[0]["kind"] == "image"
    assert inputs[0]["sha256"] == expected_sha
    assert inputs[0]["ref"] == f"uploads/{expected_sha}.jpg"
    assert "bytes" not in inputs[0]
    assert "raw_bytes" not in inputs[0]

    # Payload verification
    assert ev["payload"]["ad_hoc_upload"] is True
    assert ev["payload"]["verified_sha256"][inputs[0]["ref"]] == expected_sha


def test_upload_evidence_holds_sha256_not_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "STORE", FileStore(tmp_path / "store"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    set_test_adapter(FakeVisionAdapter())

    client = TestClient(api_mod.app)
    fake_img = b"\xff\xd8\xff\xe0" + b"EVIDENCE_SHA_CHECK" * 20 + b"\xff\xd9"
    expected_sha = hashlib.sha256(fake_img).hexdigest()

    resp = client.post(
        "/api/stages/pack/run-upload",
        files={"file": ("photo.png", fake_img, "image/png")},
        data={"unit_id": "UNIT-0010", "order_lines": "SKU-BEV-001:1"},
        headers={"X-Org-Id": "org_demo_alpha"},
    )
    assert resp.status_code == 200
    ev = resp.json()["evidence"]

    # Assert SHA256 is present and matches exactly
    inp = ev["inputs"][0]
    assert inp["sha256"] == expected_sha
    assert len(inp["sha256"]) == 64

    # Assert raw bytes or base64 are NOT present anywhere in evidence
    ev_str = json.dumps(ev)
    assert "EVIDENCE_SHA_CHECK" not in ev_str
    assert "data:image" not in ev_str
    assert "base64" not in ev_str


def test_upload_oversize_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "STORE", FileStore(tmp_path / "store"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))

    client = TestClient(api_mod.app)
    # 5 MB exceeds the 4.5 MB limit
    oversize_bytes = b"X" * (5 * 1024 * 1024)

    resp = client.post(
        "/api/stages/pack/run-upload",
        files={"file": ("huge.jpg", oversize_bytes, "image/jpeg")},
        data={"unit_id": "UNIT-0010"},
        headers={"X-Org-Id": "org_demo_alpha"},
    )
    assert resp.status_code == 413
    assert "File too large" in resp.json()["detail"]


def test_upload_unsupported_file_type(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "STORE", FileStore(tmp_path / "store"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))

    client = TestClient(api_mod.app)

    # Reject text file
    resp = client.post(
        "/api/stages/pack/run-upload",
        files={"file": ("document.txt", b"some text", "text/plain")},
        data={"unit_id": "UNIT-0010"},
        headers={"X-Org-Id": "org_demo_alpha"},
    )
    assert resp.status_code == 422
    assert "Unsupported file" in resp.json()["detail"]

    # Reject pdf file
    resp_pdf = client.post(
        "/api/stages/pack/run-upload",
        files={"file": ("document.pdf", b"%PDF-1.4...", "application/pdf")},
        data={"unit_id": "UNIT-0010"},
        headers={"X-Org-Id": "org_demo_alpha"},
    )
    assert resp_pdf.status_code == 422


def test_upload_wrong_tenant_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "STORE", FileStore(tmp_path / "store"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))

    client = TestClient(api_mod.app)
    fake_img = b"\xff\xd8\xff\xe0" + b"TENANT_CHECK" * 5 + b"\xff\xd9"

    # UNIT-0043 belongs to org_demo_bravo in dev data. Requesting under org_demo_alpha must be refused (404).
    resp = client.post(
        "/api/stages/pack/run-upload",
        files={"file": ("box.jpg", fake_img, "image/jpeg")},
        data={"unit_id": "UNIT-0043"},
        headers={"X-Org-Id": "org_demo_alpha"},
    )
    assert resp.status_code == 404


def test_upload_offline_no_api_key_returns_uncertain(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "STORE", FileStore(tmp_path / "store"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    set_test_adapter(None)  # ensure real adapter is used without api key

    client = TestClient(api_mod.app)
    fake_img = b"\xff\xd8\xff\xe0" + b"OFFLINE_IMAGE" * 10 + b"\xff\xd9"

    resp = client.post(
        "/api/stages/pack/run-upload",
        files={"file": ("box.jpg", fake_img, "image/jpeg")},
        data={"unit_id": "UNIT-0010", "order_lines": "SKU-BEV-001:1"},
        headers={"X-Org-Id": "org_demo_alpha"},
    )
    assert resp.status_code == 200
    data = resp.json()
    ev = data["evidence"]
    # ModelProviderError caught -> honest UNCERTAIN
    assert ev["decision"]["verdict"] == "UNCERTAIN"
    assert ev["status"] == "error"
    assert ev["error"]["code"] == "model_error"
    assert "Vision key not configured on this server" in ev["error"]["message"]


def test_upload_multiple_images_success(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "STORE", FileStore(tmp_path / "store"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    set_test_adapter(FakeVisionAdapter())

    client = TestClient(api_mod.app)
    img1 = b"\xff\xd8\xff\xe0" + b"ANGLE_ONE" * 10 + b"\xff\xd9"
    img2 = b"\xff\xd8\xff\xe0" + b"ANGLE_TWO" * 10 + b"\xff\xd9"
    img3 = b"\xff\xd8\xff\xe0" + b"ANGLE_THREE" * 10 + b"\xff\xd9"

    sha1 = hashlib.sha256(img1).hexdigest()
    sha2 = hashlib.sha256(img2).hexdigest()
    sha3 = hashlib.sha256(img3).hexdigest()

    resp = client.post(
        "/api/stages/pack/run-upload",
        files=[
            ("files", ("angle1.jpg", img1, "image/jpeg")),
            ("files", ("angle2.jpg", img2, "image/jpeg")),
            ("files", ("angle3.jpg", img3, "image/jpeg")),
        ],
        data={
            "unit_id": "UNIT-0010",
            "order_id": "ORD-TEST-999",
            "order_lines": json.dumps([{"sku": "SKU-BEV-001", "qty": 1}]),
        },
        headers={"X-Org-Id": "org_demo_alpha"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ev = data["evidence"]
    assert len(ev["inputs"]) == 3
    assert [inp["sha256"] for inp in ev["inputs"]] == [sha1, sha2, sha3]
    # Verify order_id recorded in payload
    assert ev["payload"]["order_id"] == "ORD-TEST-999"


def test_upload_too_many_images_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "STORE", FileStore(tmp_path / "store"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))

    client = TestClient(api_mod.app)
    img = b"\xff\xd8\xff\xe0" + b"IMG" + b"\xff\xd9"

    # Send 6 images (exceeds max 5)
    upload_files = [("files", (f"img_{i}.jpg", img, "image/jpeg")) for i in range(6)]
    resp = client.post(
        "/api/stages/pack/run-upload",
        files=upload_files,
        data={"unit_id": "UNIT-0010"},
        headers={"X-Org-Id": "org_demo_alpha"},
    )
    assert resp.status_code == 422
    assert "Maximum 5 photographs allowed" in resp.json()["detail"]


def test_upload_total_payload_oversize_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "STORE", FileStore(tmp_path / "store"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))

    client = TestClient(api_mod.app)
    # 2 images of 2.5 MB each = 5 MB total (exceeds 4.5 MB total limit even though each is <= 4 MB)
    img1 = b"\xff\xd8\xff\xe0" + b"A" * int(2.5 * 1024 * 1024) + b"\xff\xd9"
    img2 = b"\xff\xd8\xff\xe0" + b"B" * int(2.5 * 1024 * 1024) + b"\xff\xd9"

    resp = client.post(
        "/api/stages/pack/run-upload",
        files=[
            ("files", ("img1.jpg", img1, "image/jpeg")),
            ("files", ("img2.jpg", img2, "image/jpeg")),
        ],
        data={"unit_id": "UNIT-0010"},
        headers={"X-Org-Id": "org_demo_alpha"},
    )
    assert resp.status_code == 413
    assert "Total payload size" in resp.json()["detail"]

