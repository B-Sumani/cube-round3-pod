import pytest

from agents.pack.engine import (
    AGENT_ID,
    run_pack_pipeline,
    set_test_adapter,
)
from agents.pack.model_adapter import MockVisionAdapter
from agents.pack.parser import ImageQuality, ModelObservation, ObservedItem
from shared.utils.hashing import verify
from shared.utils.schema import errors


def make_test_request(
    org_id="org_demo_alpha",
    unit_id="UNIT-0008",
    inputs=None,
    previous_evidence=None,
    context=None,
):
    wf = f"WF-{org_id}-{unit_id}"
    return {
        "schema_version": "1.0",
        "request_id": f"{wf}:pack",
        "workflow_id": wf,
        "stage": "pack",
        "subject": {"org_id": org_id, "subject_id": unit_id, "route": "mfn"},
        "inputs": inputs or [],
        "previous_evidence": previous_evidence or [],
        "context": context or {},
    }


def test_sample_replay_when_inputs_empty():
    req = make_test_request("org_demo_alpha", "UNIT-0008")
    out = run_pack_pipeline(req)
    assert errors("agent-output", out) == []
    ev = out["evidence"]
    assert ev["model"]["name"] == "sample-replay"
    assert ev["payload"]["source"] == "sample_replay"
    assert ev["record_id"] == "PCK-0008"
    assert out["verdict"] == "PASS"
    assert verify(ev)


def test_deterministic_record_id_and_content_hash():
    req = make_test_request("org_demo_alpha", "UNIT-0008")
    out1 = run_pack_pipeline(req)
    out2 = run_pack_pipeline(req)
    assert out1["evidence"]["record_id"] == out2["evidence"]["record_id"]
    assert out1["evidence"]["content_hash"] == out2["evidence"]["content_hash"]


def test_tenancy_unknown_org_raises_lookup_error():
    req = make_test_request("org_intruder", "UNIT-0008")
    with pytest.raises(LookupError):
        run_pack_pipeline(req)


def test_tenancy_cross_tenant_unit_raises_lookup_error():
    # UNIT-0006 belongs to bravo, asking under alpha must raise LookupError
    req = make_test_request("org_demo_alpha", "UNIT-0006")
    with pytest.raises(LookupError):
        run_pack_pipeline(req)


def test_path_traversal_in_image_ref_raises_lookup_error(tmp_path, monkeypatch):
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    bad_req = make_test_request(
        "org_demo_alpha",
        "UNIT-0008",
        inputs=[{"ref": "../../etc/passwd", "kind": "image", "sha256": None}],
    )
    with pytest.raises(LookupError):
        run_pack_pipeline(bad_req)


def test_missing_api_key_fails_open_with_model_error(tmp_path, monkeypatch):
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    set_test_adapter(None)  # ensure real adapter is attempted

    # Create dummy image in input directory
    folder = tmp_path / "UNIT-0008" / "pack"
    folder.mkdir(parents=True)
    img_file = folder / "box.jpg"
    img_file.write_bytes(b"\xff\xd8fakejpeg")

    req = make_test_request(
        "org_demo_alpha",
        "UNIT-0008",
        inputs=[{"ref": "UNIT-0008/pack/box.jpg", "kind": "image", "sha256": None}],
        context={"case": {"order_lines": "SKU-BOTTLE-750:1"}},
    )
    out = run_pack_pipeline(req)
    assert errors("agent-output", out) == []
    assert out["verdict"] == "UNCERTAIN"
    assert out["status"] in ("pending", "error")
    assert out["error"]["code"] == "model_error"


def test_injected_mock_adapter_runs_with_real_image(tmp_path, monkeypatch):
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    folder = tmp_path / "UNIT-0008" / "pack"
    folder.mkdir(parents=True)
    img_file = folder / "box.jpg"
    img_file.write_bytes(b"\xff\xd8fakejpeg")

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-BOTTLE-750", count=1, count_confidence=0.95, identity_confidence=0.95)],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)
    set_test_adapter(mock)

    req = make_test_request(
        "org_demo_alpha",
        "UNIT-0008",
        inputs=[{"ref": "UNIT-0008/pack/box.jpg", "kind": "image", "sha256": None}],
        context={"case": {"order_lines": "SKU-BOTTLE-750:1"}},
    )
    out = run_pack_pipeline(req)
    assert errors("agent-output", out) == []
    assert out["verdict"] == "PASS"
    assert out["evidence"]["payload"]["source"] == "vision_pipeline"
    assert mock.call_count == 1
    # Clean up test adapter
    set_test_adapter(None)


def test_exif_capture_time_extracted_from_jpeg(tmp_path, monkeypatch):
    import struct
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))

    # Construct minimal JPEG with APP1 EXIF containing DateTimeOriginal
    date_str = "2026:05:20 11:22:33"
    date_bytes = date_str.encode("ascii") + b"\x00"
    ifd0 = struct.pack("<H", 1) + struct.pack("<HHI4s", 0x9003, 2, len(date_bytes), struct.pack("<I", 26)) + struct.pack("<I", 0) + date_bytes
    tiff = b"II\x2a\x00\x08\x00\x00\x00" + ifd0
    app1 = b"Exif\x00\x00" + tiff
    app1_marker = b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1
    jpeg_bytes = b"\xff\xd8" + app1_marker + b"\xff\xd9"

    img_file = tmp_path / "exif_box.jpg"
    img_file.write_bytes(jpeg_bytes)

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-BOTTLE-750", count=1, count_confidence=0.95, identity_confidence=0.95)],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)

    req = make_test_request(
        "org_demo_alpha",
        "UNIT-0008",
        inputs=[{"ref": "exif_box.jpg", "kind": "image", "sha256": None}],
        context={"case": {"order_lines": "SKU-BOTTLE-750:1"}},
    )
    out = run_pack_pipeline(req, adapter=mock)
    ev = out["evidence"]
    assert ev["captured_at"] == "2026-05-20T11:22:33Z"
    assert ev["payload"]["captured_at_source"] == "exif"


def test_multi_image_earliest_mtime_chosen(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))

    img1 = tmp_path / "img1.jpg"
    img2 = tmp_path / "img2.jpg"
    img1.write_bytes(b"content-1")
    img2.write_bytes(b"content-2")

    # Set explicit distinct mtimes (img1 earlier than img2)
    t_earlier = 1770000000.0  # 2026-02-02
    t_later = 1780000000.0    # 2026-05-28
    os.utime(img1, (t_earlier, t_earlier))
    os.utime(img2, (t_later, t_later))

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-BOTTLE-750", count=1, count_confidence=0.95, identity_confidence=0.95)],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)

    req = make_test_request(
        "org_demo_alpha",
        "UNIT-0008",
        inputs=[
            {"ref": "img2.jpg", "kind": "image", "sha256": None},
            {"ref": "img1.jpg", "kind": "image", "sha256": None},
        ],
        context={"case": {"order_lines": "SKU-BOTTLE-750:1"}},
    )
    out = run_pack_pipeline(req, adapter=mock)
    ev = out["evidence"]

    # Must be earliest timestamp (img1)
    from datetime import datetime, timezone
    expected_iso = datetime.fromtimestamp(t_earlier, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert ev["captured_at"] == expected_iso
    assert ev["payload"]["captured_at_source"] == "file_mtime"
    assert mock.call_count == 1
    assert len(mock.last_images) == 2
