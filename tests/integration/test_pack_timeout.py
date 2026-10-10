"""Integration tests for Pack vision model timeout, retry, image downscaling, and review queue integration."""
import base64
import hashlib
import io
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from PIL import Image
import httpx
import pytest

import orchestration.api as api_mod
from orchestration.store import FileStore
from agents.pack.engine import set_test_adapter
from agents.pack.app import handle as pack_handle
from agents.pack.model_adapter import (
    GeminiVisionAdapter,
    MockVisionAdapter,
    ModelTimeoutError,
    ModelProviderError,
    _prepare_image_for_model,
)


@pytest.fixture(autouse=True)
def cleanup_adapter():
    yield
    set_test_adapter(None)


def test_prepare_image_downscales_to_1280_max():
    """Verify server-side adapter downscales images > 1280px to exactly max 1280px and JPEG quality ~80."""
    orig_img = Image.new("RGB", (2000, 1500), color="blue")
    buf = io.BytesIO()
    orig_img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    downscaled_bytes, mime_type = _prepare_image_for_model(png_bytes, max_dim=1280, quality=80)
    assert mime_type == "image/jpeg"

    with Image.open(io.BytesIO(downscaled_bytes)) as res_img:
        width, height = res_img.size
        assert max(width, height) == 1280
        assert width == 1280
        assert height == 960
        assert res_img.format == "JPEG"


def test_prepare_image_preserves_smaller_images_without_upscaling():
    """Images with dimensions under 1280px are re-encoded to JPEG without upscaling."""
    orig_img = Image.new("RGB", (800, 600), color="green")
    buf = io.BytesIO()
    orig_img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    downscaled_bytes, mime_type = _prepare_image_for_model(png_bytes, max_dim=1280, quality=80)
    assert mime_type == "image/jpeg"

    with Image.open(io.BytesIO(downscaled_bytes)) as res_img:
        assert res_img.size == (800, 600)
        assert res_img.format == "JPEG"


def test_adapter_retries_once_on_timeout():
    """Verify GeminiVisionAdapter retries once on timeout within budget, then raises ModelTimeoutError."""
    adapter = GeminiVisionAdapter(
        api_key="test-key-12345",
        total_timeout_budget=10.0,
        max_transport_retries=1,
    )

    fake_img = b"\xff\xd8\xff\xe0" + b"TEST" * 10 + b"\xff\xd9"

    with patch("httpx.Client.post") as mock_post:
        mock_post.side_effect = [
            httpx.ReadTimeout("The read operation timed out"),
            httpx.ReadTimeout("The read operation timed out"),
        ]

        with pytest.raises(ModelTimeoutError) as exc_info:
            adapter.analyze_box(images=[fake_img], candidate_skus=["SKU-001"])

        assert "timed out" in str(exc_info.value).lower()
        # Exactly 2 calls: initial attempt + 1 retry
        assert mock_post.call_count == 2


def test_adapter_never_retries_on_auth_or_bad_request():
    """Verify GeminiVisionAdapter does NOT retry on HTTP 400 or HTTP 401/403."""
    adapter = GeminiVisionAdapter(
        api_key="test-key-12345",
        total_timeout_budget=10.0,
        max_transport_retries=1,
    )
    fake_img = b"\xff\xd8\xff\xe0" + b"TEST" * 10 + b"\xff\xd9"

    for status_code in (400, 401, 403):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.text = f"Client Error {status_code}"

        with patch("httpx.Client.post") as mock_post:
            mock_post.return_value = mock_resp

            with pytest.raises(ModelProviderError) as exc_info:
                adapter.analyze_box(images=[fake_img], candidate_skus=["SKU-001"])

            assert str(status_code) in str(exc_info.value)
            # Never retried: exactly 1 call
            assert mock_post.call_count == 1


def test_engine_returns_model_timeout_uncertain_and_original_hash(tmp_path, monkeypatch):
    """When vision call times out, engine returns UNCERTAIN with code=model_timeout, never a fake PASS,
    and original evidence hash is preserved.
    """
    img = Image.new("RGB", (1600, 1200), color="red")
    img_buf = io.BytesIO()
    img.save(img_buf, format="JPEG")
    orig_img_bytes = img_buf.getvalue()
    orig_sha = hashlib.sha256(orig_img_bytes).hexdigest()

    # Save to upload dir
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True)
    img_path = upload_dir / "test_box.jpg"
    img_path.write_bytes(orig_img_bytes)
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))

    # Inject timeout adapter
    set_test_adapter(MockVisionAdapter(simulate_timeout=True))

    agent_input = {
        "schema_version": "1.0",
        "request_id": "req-timeout-test-1",
        "workflow_id": "WF-org_demo_alpha-UNIT-TIMEOUT-1",
        "stage": "pack",
        "subject": {
            "org_id": "org_demo_alpha",
            "subject_id": "UNIT-TIMEOUT-1",
            "route": "mfn",
        },
        "inputs": [
            {
                "ref": "uploads/test_box.jpg",
                "kind": "image",
                "sha256": orig_sha,
            }
        ],
        "previous_evidence": [],
        "context": {
            "order_lines": "SKU-BEV-001:1",
            "ad_hoc_upload": True,
        },
    }

    out = pack_handle(agent_input)

    # Must be UNCERTAIN (never a fake PASS)
    assert out["verdict"] == "UNCERTAIN"
    assert out["status"] == "pending"
    assert out["error"]["code"] == "model_timeout"
    assert out["error"]["retryable"] is True
    assert "The vision model timed out. Try again or use fewer or smaller photos." in out["error"]["message"]

    # Evidence Record checks
    ev = out["evidence"]
    assert ev["decision"]["verdict"] == "UNCERTAIN"
    assert ev["decision"]["needs_human"] is True
    assert ev["status"] == "pending"
    # Original SHA-256 of uploaded file is preserved in inputs, not resized copy
    assert ev["inputs"][0]["sha256"] == orig_sha
    assert ev["payload"]["image_sha256"]["uploads/test_box.jpg"] == orig_sha


def test_upload_endpoint_timeout_appears_in_review_queue(tmp_path, monkeypatch):
    """When an upload times out via POST /api/stages/pack/run-upload, it is recorded and appears in the review queue."""
    store = FileStore(tmp_path / "store")
    monkeypatch.setattr(api_mod, "STORE", store)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    set_test_adapter(MockVisionAdapter(simulate_timeout=True))
    client = TestClient(api_mod.app)

    org = "org_demo_alpha"
    img = Image.new("RGB", (1400, 1000), color="yellow")
    img_buf = io.BytesIO()
    img.save(img_buf, format="JPEG")
    fake_img = img_buf.getvalue()

    resp = client.post(
        "/api/stages/pack/run-upload",
        files={"file": ("box_timeout.jpg", fake_img, "image/jpeg")},
        data={"unit_id": "UNIT-TIMEOUT-REVIEW", "order_lines": "SKU-BEV-001:1"},
        headers={"X-Org-Id": org},
    )
    assert resp.status_code == 200, resp.text
    res_data = resp.json()

    assert res_data["evidence"]["decision"]["verdict"] == "UNCERTAIN"
    assert res_data["evidence"]["error"]["code"] == "model_timeout"

    # Query Review Queue
    q_resp = client.get("/api/review", headers={"X-Org-Id": org})
    assert q_resp.status_code == 200
    q_data = q_resp.json()

    item = next((it for it in q_data["pending"] if it["unit_id"] == "UNIT-TIMEOUT-REVIEW"), None)
    assert item is not None
    assert item["stage"] == "pack"
    assert item["verdict"] == "UNCERTAIN"
    assert item["needs_human"] is True
    assert "model_timeout" in item["reason"]
