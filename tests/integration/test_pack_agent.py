"""Integration tests for the Pack Manager agent (agents/pack).

Tests end-to-end integration via orchestration.clients.client_for("pack")
as well as direct engine execution with vision adapters.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from agents.pack.engine import run_pack_pipeline
from agents.pack.model_adapter import MockVisionAdapter
from agents.pack.parser import ModelObservation, ObservedItem, UnrecognisedItem, ImageQuality
from agents.pack.tests.test_pack_contract_suite import (
    test_pack_contract,
    test_pack_fail,
    test_pack_hash,
    test_pack_invalid_agent_input_rejected,
    test_pack_model_failure,
    test_pack_pass,
    test_pack_previous_evidence,
    test_pack_quantities_correct_omitted_when_no_items_present,
    test_pack_uncertain,
    test_pack_wrong_tenant,
)
from orchestration.clients import AgentRejected, client_for
from shared.utils.hashing import verify
from shared.utils.schema import errors
from tests.conftest import applies, make_input

ROOT = Path(__file__).resolve().parents[2]
PCK_ID_REGEX = re.compile(r"^PCK-[A-Za-z0-9._-]+$")


def test_pack_mfn_cases_are_contract_valid(cases):
    """Every MFN case evaluated by the pack agent produces contract-valid output and evidence."""
    client = client_for("pack")
    mfn_cases = [c for c in cases if applies("pack", c)]
    assert len(mfn_cases) > 0, "Expected at least one MFN case in sample cases"

    for case in mfn_cases:
        req = make_input("pack", case)
        out = client.run(req, 30)

        assert errors("agent-output", out) == [], f"Validation failed for {case['unit_id']}"
        ev = out["evidence"]
        assert errors("evidence", ev) == []
        assert verify(ev), f"Evidence content_hash failed verification for {case['unit_id']}"

        assert out["stage"] == "pack"
        assert out["agent_id"] == "pack-manager@1.0.0"
        assert PCK_ID_REGEX.match(ev["record_id"]), f"Invalid record_id: {ev['record_id']}"

        # Standard check keys: items_present and no_extra_items are always present;
        # quantities_correct applies only when at least one expected item is present
        # (non-applicable checks are omitted per EVIDENCE-CONTRACT.md line 93).
        check_keys = {c["check_key"] for c in ev["checks"]}
        assert {"items_present", "no_extra_items"}.issubset(check_keys)
        assert check_keys.issubset({"items_present", "quantities_correct", "no_extra_items"})

        # Verdict consistency
        assert out["verdict"] == ev["decision"]["verdict"]
        assert out["status"] == ev["status"]


def test_pack_tenancy_rejection(cases):
    """Asking for a pack unit under the wrong org must be refused with AgentRejected (LookupError)."""
    client = client_for("pack")
    case = next(c for c in cases if applies("pack", c))

    wrong_org = "org_demo_bravo" if case["org_id"] == "org_demo_alpha" else "org_demo_alpha"
    mismatched_req = make_input("pack", {**case, "org_id": wrong_org})
    with pytest.raises(AgentRejected):
        client.run(mismatched_req, 30)

    unknown_req = make_input("pack", {**case, "org_id": "org_nonexistent"})
    with pytest.raises(AgentRejected):
        client.run(unknown_req, 30)


def test_pack_deterministic_record_id_and_content_hash(cases):
    """Identical requests must produce the exact same record_id and identical content_hash."""
    client = client_for("pack")
    case = next(c for c in cases if applies("pack", c))
    req = make_input("pack", case)

    res1 = client.run(req, 30)
    res2 = client.run(req, 30)

    assert res1["evidence"]["record_id"] == res2["evidence"]["record_id"]
    assert res1["evidence"]["content_hash"] == res2["evidence"]["content_hash"]
    assert verify(res1["evidence"])
    assert verify(res2["evidence"])


def test_pack_upstream_refs_only_includes_receiving(cases):
    """Pack manager must include only Receiving record IDs in upstream_refs and honor overrides."""
    from shared.utils.records import build_record

    case = next(c for c in cases if applies("pack", c))
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
    req = make_input("pack", case, previous=[rcv_ev, prep_ev], overrides=overrides)

    out = client_for("pack").run(req, 30)
    ev = out["evidence"]

    # upstream_refs should strictly contain only the receiving record
    assert ev["upstream_refs"] == [rcv_ev["record_id"]]
    # upstream_verdicts in payload must reflect the overridden verdict
    assert ev["payload"]["upstream_verdicts"][rcv_ev["record_id"]] == "FAIL"


def test_pack_vision_pipeline_matching_items(tmp_path, monkeypatch):
    """End-to-end vision pipeline: mock observes exact order lines -> SEAL (PASS)."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img_file = tmp_path / "carton.jpg"
    img_content = b"fake-jpg-content-for-testing"
    img_file.write_bytes(img_content)
    img_sha256 = hashlib.sha256(img_content).hexdigest()

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-001", count=1, count_confidence=0.95, identity_confidence=0.95, bbox=[10, 10, 100, 100])],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
    )

    req = {
        "schema_version": "1.0",
        "request_id": "REQ-001",
        "workflow_id": "WF-alpha-001",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-1"},
        "inputs": [{"kind": "image", "ref": "carton.jpg", "sha256": img_sha256}],
        "context": {"order_lines": [{"sku": "SKU-001", "quantity": 1}]},
    }

    out = run_pack_pipeline(req, adapter=MockVisionAdapter(obs))
    assert errors("agent-output", out) == []
    assert out["verdict"] == "PASS"
    assert out["status"] == "completed"
    assert out["evidence"]["payload"]["source"] == "vision_pipeline"


def test_pack_vision_pipeline_missing_item(tmp_path, monkeypatch):
    """End-to-end vision pipeline: expected SKU missing -> STOP_AND_FIX (FAIL)."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img_file = tmp_path / "carton.jpg"
    img_content = b"fake-jpg-content-for-testing"
    img_file.write_bytes(img_content)
    img_sha256 = hashlib.sha256(img_content).hexdigest()

    obs = ModelObservation(
        observed_items=[],  # SKU-001 missing
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
    )

    req = {
        "schema_version": "1.0",
        "request_id": "REQ-002",
        "workflow_id": "WF-alpha-002",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-2"},
        "inputs": [{"kind": "image", "ref": "carton.jpg", "sha256": img_sha256}],
        "context": {"order_lines": [{"sku": "SKU-001", "quantity": 1}]},
    }

    out = run_pack_pipeline(req, adapter=MockVisionAdapter(obs))
    assert errors("agent-output", out) == []
    assert out["verdict"] == "FAIL"
    assert out["status"] == "completed"
    assert out["evidence"]["decision"]["outcome"] == "stop_and_fix"
    assert "MISSING_ITEMS" in out["evidence"]["payload"]["reason_codes"].values()


def test_pack_vision_pipeline_unrecognised_item(tmp_path, monkeypatch):
    """End-to-end vision pipeline: unexpected extra item -> STOP_AND_FIX (FAIL)."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img_file = tmp_path / "carton.jpg"
    img_content = b"fake-jpg-content-for-testing"
    img_file.write_bytes(img_content)
    img_sha256 = hashlib.sha256(img_content).hexdigest()

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-001", count=1, count_confidence=0.95, identity_confidence=0.95)],
        unrecognised_items=[UnrecognisedItem(description="unknown gadget", bbox=[0, 0, 0, 0])],
        image_quality=ImageQuality(usable=True, issues=[]),
    )

    req = {
        "schema_version": "1.0",
        "request_id": "REQ-003",
        "workflow_id": "WF-alpha-003",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-3"},
        "inputs": [{"kind": "image", "ref": "carton.jpg", "sha256": img_sha256}],
        "context": {"order_lines": [{"sku": "SKU-001", "quantity": 1}]},
    }

    out = run_pack_pipeline(req, adapter=MockVisionAdapter(obs))
    assert errors("agent-output", out) == []
    assert out["verdict"] == "FAIL"
    assert "UNRECOGNISED_ITEMS_PRESENT" in out["evidence"]["payload"]["reason_codes"].values()


def test_pack_vision_pipeline_blur_causes_uncertain(tmp_path, monkeypatch):
    """End-to-end vision pipeline: blurry image -> UNCERTAIN with image_blur."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img_file = tmp_path / "carton.jpg"
    img_content = b"fake-jpg-content-for-testing"
    img_file.write_bytes(img_content)
    img_sha256 = hashlib.sha256(img_content).hexdigest()

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-001", count=1, count_confidence=0.95, identity_confidence=0.95)],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=False, issues=["blur"]),
    )

    req = {
        "schema_version": "1.0",
        "request_id": "REQ-004",
        "workflow_id": "WF-alpha-004",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-4"},
        "inputs": [{"kind": "image", "ref": "carton.jpg", "sha256": img_sha256}],
        "context": {"order_lines": [{"sku": "SKU-001", "quantity": 1}]},
    }

    out = run_pack_pipeline(req, adapter=MockVisionAdapter(obs))
    assert errors("agent-output", out) == []
    assert out["verdict"] == "UNCERTAIN"
    assert "IMAGE_UNUSABLE" in out["evidence"]["payload"]["reason_codes"].values()


def test_pack_missing_image_ref():
    """Missing image file yields UNCERTAIN (insufficient_evidence)."""
    fake_sha = hashlib.sha256(b"nonexistent").hexdigest()
    req = {
        "schema_version": "1.0",
        "request_id": "REQ-005",
        "workflow_id": "WF-alpha-005",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-5"},
        "inputs": [{"kind": "image", "ref": "nonexistent_file.jpg", "sha256": fake_sha}],
        "context": {"order_lines": [{"sku": "SKU-001", "quantity": 1}]},
    }
    out = run_pack_pipeline(req)
    assert errors("agent-output", out) == []
    assert out["verdict"] == "UNCERTAIN"
    assert out["status"] == "completed"
    check = out["evidence"]["checks"][0]
    assert check["uncertain_reason"] == "insufficient_evidence"


def test_pack_directory_traversal_ref():
    """Directory traversal in image ref escapes INPUT_DIR and is rejected with LookupError / AgentRejected."""
    req = {
        "schema_version": "1.0",
        "request_id": "REQ-006",
        "workflow_id": "WF-alpha-006",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-6"},
        "inputs": [{"kind": "image", "ref": "../../etc/passwd.jpg", "sha256": "0" * 64}],
        "previous_evidence": [],
        "context": {"order_lines": [{"sku": "SKU-001", "quantity": 1}]},
    }
    # When executed through orchestrator client, LookupError translates to AgentRejected
    with pytest.raises(AgentRejected):
        client_for("pack").run(req, 30)


def test_pack_sha256_mismatch(tmp_path, monkeypatch):
    """SHA-256 hash mismatch yields UNCERTAIN (conflicting_evidence)."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img_file = tmp_path / "carton.jpg"
    img_file.write_bytes(b"actual-content")

    req = {
        "schema_version": "1.0",
        "request_id": "REQ-007",
        "workflow_id": "WF-alpha-007",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-7"},
        "inputs": [{"kind": "image", "ref": "carton.jpg", "sha256": "0" * 64}],
        "context": {"order_lines": [{"sku": "SKU-001", "quantity": 1}]},
    }
    out = run_pack_pipeline(req)
    assert errors("agent-output", out) == []
    assert out["verdict"] == "UNCERTAIN"
    check = out["evidence"]["checks"][0]
    assert check["uncertain_reason"] == "conflicting_evidence"


def test_pack_missing_order_lines():
    """Request with no order lines available yields UNCERTAIN (insufficient_evidence)."""
    req = {
        "schema_version": "1.0",
        "request_id": "REQ-008",
        "workflow_id": "WF-alpha-008",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-NONEXISTENT-NO-LINES"},
        "inputs": [],
        "context": {},
    }
    out = run_pack_pipeline(req)
    assert errors("agent-output", out) == []
    assert out["verdict"] == "UNCERTAIN"
    check = out["evidence"]["checks"][0]
    assert check["uncertain_reason"] == "insufficient_evidence"


def test_pack_no_api_key_returns_uncertain_model_error(monkeypatch, tmp_path):
    """When GEMINI_API_KEY is missing, vision pipeline returns UNCERTAIN with model_error."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))

    img_file = tmp_path / "carton.jpg"
    img_content = b"fake-jpg"
    img_file.write_bytes(img_content)
    img_sha256 = hashlib.sha256(img_content).hexdigest()

    req = {
        "schema_version": "1.0",
        "request_id": "REQ-009",
        "workflow_id": "WF-alpha-009",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-9"},
        "inputs": [{"kind": "image", "ref": "carton.jpg", "sha256": img_sha256}],
        "context": {"order_lines": [{"sku": "SKU-001", "quantity": 1}]},
    }

    out = run_pack_pipeline(req)
    assert errors("agent-output", out) == []
    assert out["verdict"] == "UNCERTAIN"
    assert out["status"] == "error"
    assert out["error"]["code"] == "model_error"


def test_hash_mismatch_on_second_image_gives_uncertain_zero_model_calls(tmp_path, monkeypatch):
    """A hash mismatch on the second image must yield UNCERTAIN with zero model calls and offending ref."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img1 = tmp_path / "box_top.jpg"
    img2 = tmp_path / "box_side.jpg"
    img1.write_bytes(b"content-1")
    img2.write_bytes(b"content-2")

    sha1 = hashlib.sha256(b"content-1").hexdigest()
    bad_sha2 = "f" * 64

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-001", count=1, count_confidence=0.95, identity_confidence=0.95)],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)

    req = {
        "schema_version": "1.0",
        "request_id": "REQ-MULTI-HASH-FAIL",
        "workflow_id": "WF-alpha-multi-1",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-M1"},
        "inputs": [
            {"kind": "image", "ref": "box_top.jpg", "sha256": sha1},
            {"kind": "image", "ref": "box_side.jpg", "sha256": bad_sha2},
        ],
        "context": {"order_lines": "SKU-001:1"},
    }

    out = run_pack_pipeline(req, adapter=mock)
    assert errors("agent-output", out) == []
    assert out["verdict"] == "UNCERTAIN"
    assert mock.call_count == 0, "No model calls allowed on hash mismatch"
    assert out["evidence"]["model"]["calls"] == 0

    ev = out["evidence"]
    assert ev["decision"]["verdict"] == "UNCERTAIN"
    check = ev["checks"][0]
    assert check["uncertain_reason"] == "conflicting_evidence"
    assert "box_side.jpg" in check["detail"]
    assert ev["payload"]["offending_ref"] == "box_side.jpg"


def test_missing_second_image_file_gives_uncertain_zero_model_calls(tmp_path, monkeypatch):
    """A missing second image file must yield UNCERTAIN with zero model calls and offending ref."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img1 = tmp_path / "box_top.jpg"
    img1.write_bytes(b"content-1")
    sha1 = hashlib.sha256(b"content-1").hexdigest()
    sha2 = hashlib.sha256(b"content-2").hexdigest()

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-001", count=1, count_confidence=0.95, identity_confidence=0.95)],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)

    req = {
        "schema_version": "1.0",
        "request_id": "REQ-MULTI-MISSING-FAIL",
        "workflow_id": "WF-alpha-multi-2",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-M2"},
        "inputs": [
            {"kind": "image", "ref": "box_top.jpg", "sha256": sha1},
            {"kind": "image", "ref": "box_side.jpg", "sha256": sha2},  # box_side.jpg does not exist
        ],
        "context": {"order_lines": "SKU-001:1"},
    }

    out = run_pack_pipeline(req, adapter=mock)
    assert errors("agent-output", out) == []
    assert out["verdict"] == "UNCERTAIN"
    assert mock.call_count == 0, "No model calls allowed when image is missing"
    assert out["evidence"]["model"]["calls"] == 0

    ev = out["evidence"]
    assert ev["decision"]["verdict"] == "UNCERTAIN"
    check = ev["checks"][0]
    assert check["uncertain_reason"] == "insufficient_evidence"
    assert "box_side.jpg" in check["detail"]
    assert ev["payload"]["offending_ref"] == "box_side.jpg"


def test_two_valid_images_produce_exactly_one_model_call_and_both_reach_adapter(tmp_path, monkeypatch):
    """Two valid image inputs produce exactly one model call and both images reach the adapter."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img1 = tmp_path / "box_angle1.jpg"
    img2 = tmp_path / "box_angle2.jpg"
    content1 = b"angle-1-image-bytes"
    content2 = b"angle-2-image-bytes"
    img1.write_bytes(content1)
    img2.write_bytes(content2)
    sha1 = hashlib.sha256(content1).hexdigest()
    sha2 = hashlib.sha256(content2).hexdigest()

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-001", count=1, count_confidence=0.95, identity_confidence=0.95)],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)

    req = {
        "schema_version": "1.0",
        "request_id": "REQ-MULTI-SUCCESS",
        "workflow_id": "WF-alpha-multi-3",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-M3"},
        "inputs": [
            {"kind": "image", "ref": "box_angle1.jpg", "sha256": sha1},
            {"kind": "image", "ref": "box_angle2.jpg", "sha256": sha2},
        ],
        "context": {"order_lines": "SKU-001:1"},
    }

    out = run_pack_pipeline(req, adapter=mock)
    assert errors("agent-output", out) == []
    assert out["verdict"] == "PASS"
    assert mock.call_count == 1, "Must make exactly one model call for the unit"
    assert len(mock.last_images) == 2, "Both images must reach the vision adapter"
    assert mock.last_images[0] == content1
    assert mock.last_images[1] == content2

    ev = out["evidence"]
    assert ev["payload"]["image_refs"] == ["box_angle1.jpg", "box_angle2.jpg"]
    assert ev["payload"]["image_sha256"]["box_angle1.jpg"] == sha1
    assert ev["payload"]["image_sha256"]["box_angle2.jpg"] == sha2


def test_captured_at_not_fixed_date_and_captured_at_source_set(tmp_path, monkeypatch):
    """Non-sample request must never use a hardcoded date; payload.captured_at_source must be set."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img = tmp_path / "box.jpg"
    img.write_bytes(b"content")
    sha = hashlib.sha256(b"content").hexdigest()

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-001", count=1, count_confidence=0.95, identity_confidence=0.95)],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)

    req = {
        "schema_version": "1.0",
        "request_id": "REQ-MTIME-1",
        "workflow_id": "WF-alpha-mtime",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-MTIME"},
        "inputs": [{"kind": "image", "ref": "box.jpg", "sha256": sha}],
        "context": {"order_lines": "SKU-001:1"},
    }

    out = run_pack_pipeline(req, adapter=mock)
    ev = out["evidence"]
    assert ev["captured_at"] != "2026-10-04T12:00:00Z", "Never use a hardcoded fixed date"
    assert ev["payload"]["captured_at_source"] in ("exif", "file_mtime")
    assert ev["produced_at"] == ev["captured_at"]


def test_context_capture_time_takes_priority_over_file_mtime(tmp_path, monkeypatch):
    """Context capture time must take priority over file modified time and EXIF."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img = tmp_path / "box.jpg"
    img.write_bytes(b"content")
    sha = hashlib.sha256(b"content").hexdigest()

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-001", count=1, count_confidence=0.95, identity_confidence=0.95)],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)

    target_time = "2026-03-15T08:30:00Z"
    req = {
        "schema_version": "1.0",
        "request_id": "REQ-CTX-TIME",
        "workflow_id": "WF-alpha-ctxtime",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-CTX"},
        "inputs": [{"kind": "image", "ref": "box.jpg", "sha256": sha}],
        "context": {
            "order_lines": "SKU-001:1",
            "case": {"captured_at": target_time},
        },
    }

    out = run_pack_pipeline(req, adapter=mock)
    ev = out["evidence"]
    assert ev["captured_at"] == target_time
    assert ev["payload"]["captured_at_source"] == "context"
    assert ev["produced_at"] == target_time


def test_non_sample_same_request_twice_gives_same_record_id_and_content_hash(tmp_path, monkeypatch):
    """Non-sample request evaluated twice produces identical record_id and content_hash."""
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    img = tmp_path / "box.jpg"
    img.write_bytes(b"content")
    sha = hashlib.sha256(b"content").hexdigest()

    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-001", count=1, count_confidence=0.95, identity_confidence=0.95)],
        image_quality=ImageQuality(usable=True),
    )
    mock = MockVisionAdapter(mock_observation=obs)

    req = {
        "schema_version": "1.0",
        "request_id": "REQ-IDEMPOTENT-NON-SAMPLE",
        "workflow_id": "WF-alpha-idempotent",
        "stage": "pack",
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-CUSTOM-IDEM"},
        "inputs": [{"kind": "image", "ref": "box.jpg", "sha256": sha}],
        "context": {"order_lines": "SKU-001:1"},
    }

    out1 = run_pack_pipeline(req, adapter=mock)
    out2 = run_pack_pipeline(req, adapter=mock)

    assert out1["evidence"]["record_id"] == out2["evidence"]["record_id"]
    assert out1["evidence"]["content_hash"] == out2["evidence"]["content_hash"]
    assert verify(out1["evidence"])
    assert verify(out2["evidence"])
