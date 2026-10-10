"""Integration tests for the Review Queue API and workflow UNCERTAIN/needs_human resolution."""
from fastapi.testclient import TestClient
import pytest

import orchestration.api as api_mod
from orchestration.store import FileStore
from agents.pack.engine import set_test_adapter
from agents.pack.model_adapter import VisionModelAdapter
from agents.pack.parser import ModelObservation, ImageQuality


class UncertainVisionAdapter(VisionModelAdapter):
    def analyze_box(self, images=None, candidate_skus=None, catalogue=None, timeout_seconds=None, **kwargs):
        obs = ModelObservation(
            observed_items=[],
            image_quality=ImageQuality(usable=False, blur_detected=True),
            occlusion_suspected=True,
        )
        return obs, 45, {"name": "uncertain-vision", "version": "1.0", "calls": 1}


@pytest.fixture(autouse=True)
def cleanup_adapter():
    yield
    set_test_adapter(None)


def test_review_queue_all_five_stages_uncertain(tmp_path, monkeypatch):
    store = FileStore(tmp_path / "store")
    monkeypatch.setattr(api_mod, "STORE", store)
    client = TestClient(api_mod.app)

    org = "org_demo_alpha"
    stages = ["receiving", "prep", "pack", "returns", "recovery"]

    for i, stage in enumerate(stages):
        wf_id = f"wf-{stage}-{i}"
        unit_id = f"UNIT-{stage.upper()}-{i}"
        rec_id = f"ev-{stage}-{i}"
        rec = {
            "record_id": rec_id,
            "schema_version": "1.0",
            "workflow_id": wf_id,
            "stage": stage,
            "subject": {
                "unit_id": unit_id,
                "subject_id": unit_id,
                "org_id": org,
                "subject_type": "unit",
            },
            "decision": {
                "verdict": "UNCERTAIN",
                "reason": f"Agent {stage} flagged ambiguity requiring operator verification",
                "needs_human": True,
            },
            "created_at": "2026-10-10T10:00:00Z",
        }
        wf = {
            "schema_version": "1.0",
            "workflow_id": wf_id,
            "unit_id": unit_id,
            "subject_id": unit_id,
            "org_id": org,
            "flow_id": "standard-v1",
            "status": "BLOCKED",
            "status_reason": f"stage {stage} is UNCERTAIN",
            "stage_results": [
                {
                    "stage": stage,
                    "agent_id": f"{stage}-agent",
                    "state": "completed",
                    "verdict": "UNCERTAIN",
                    "outcome": "UNCERTAIN",
                    "needs_human": True,
                    "record_id": rec_id,
                    "runs": 1,
                    "attempts": 1,
                }
            ],
            "evidence_references": [rec_id],
            "transitions": [{"action": "run_stage", "stage": stage, "verdict": "UNCERTAIN"}],
            "overrides": [],
            "errors": [],
            "timestamps": {"created_at": "2026-10-10T10:00:00Z", "updated_at": "2026-10-10T10:00:00Z"},
        }
        store.put_evidence(rec)
        store.save_workflow(wf)

    resp = client.get("/api/review", headers={"X-Org-Id": org})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["pending_count"] == 5
    assert data["resolved_count"] == 0
    found_stages = {item["stage"] for item in data["pending"]}
    assert found_stages == set(stages)

    # Check structure of each queue item
    for item in data["pending"]:
        assert item["org_id"] == org
        assert item["verdict"] == "UNCERTAIN"
        assert item["needs_human"] is True
        assert item["evidence_record_id"] is not None
        assert "reason" in item


def test_review_queue_ad_hoc_upload_uncertain(tmp_path, monkeypatch):
    store = FileStore(tmp_path / "store")
    monkeypatch.setattr(api_mod, "STORE", store)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    set_test_adapter(UncertainVisionAdapter())
    client = TestClient(api_mod.app)

    org = "org_demo_alpha"
    fake_img = b"\xff\xd8\xff\xe0" + b"UNCERTAIN_IMG" * 10 + b"\xff\xd9"

    resp = client.post(
        "/api/stages/pack/run-upload",
        files={"file": ("box_blur.jpg", fake_img, "image/jpeg")},
        data={"unit_id": "UNIT-ADHOC-99", "order_lines": "SKU-BEV-001:1"},
        headers={"X-Org-Id": org},
    )
    assert resp.status_code == 200, resp.text
    upload_res = resp.json()
    assert upload_res["is_ad_hoc_upload"] is True
    assert upload_res["evidence"]["decision"]["verdict"] == "UNCERTAIN"

    # Verify review queue contains the ad hoc upload
    q_resp = client.get("/api/review", headers={"X-Org-Id": org})
    assert q_resp.status_code == 200
    q_data = q_resp.json()
    assert q_data["pending_count"] >= 1

    adhoc_item = next((item for item in q_data["pending"] if item["unit_id"] == "UNIT-ADHOC-99"), None)
    assert adhoc_item is not None
    assert adhoc_item["is_ad_hoc_upload"] is True
    assert adhoc_item["stage"] == "pack"
    assert adhoc_item["verdict"] == "UNCERTAIN"

    # Confirm other stages were not fabricated
    wf = store.load_workflow(adhoc_item["workflow_id"])
    assert [sr["stage"] for sr in wf["stage_results"]] == ["pack"]


def test_review_queue_override_lifecycle(tmp_path, monkeypatch):
    store = FileStore(tmp_path / "store")
    monkeypatch.setattr(api_mod, "STORE", store)
    client = TestClient(api_mod.app)

    org = "org_demo_alpha"
    wf_id = "wf-test-override"
    unit_id = "UNIT-TEST-OVERRIDE"
    rec_id = "ev-rec-override"

    original_rec = {
        "record_id": rec_id,
        "schema_version": "1.0",
        "workflow_id": wf_id,
        "stage": "pack",
        "subject": {
            "unit_id": unit_id,
            "subject_id": unit_id,
            "org_id": org,
            "subject_type": "unit",
        },
        "decision": {
            "verdict": "UNCERTAIN",
            "reason": "Blurry camera view",
            "needs_human": True,
        },
        "created_at": "2026-10-10T10:00:00Z",
    }
    wf = {
        "schema_version": "1.0",
        "workflow_id": wf_id,
        "unit_id": unit_id,
        "subject_id": unit_id,
        "org_id": org,
        "flow_id": "standard-v1",
        "status": "BLOCKED",
        "status_reason": "stage pack is UNCERTAIN",
        "stage_results": [
            {
                "stage": "pack",
                "agent_id": "pack-agent",
                "state": "completed",
                "verdict": "UNCERTAIN",
                "outcome": "UNCERTAIN",
                "needs_human": True,
                "record_id": rec_id,
                "runs": 1,
                "attempts": 1,
            }
        ],
        "evidence_references": [rec_id],
        "transitions": [{"action": "run_stage", "stage": "pack", "verdict": "UNCERTAIN"}],
        "overrides": [],
        "errors": [],
        "timestamps": {"created_at": "2026-10-10T10:00:00Z", "updated_at": "2026-10-10T10:00:00Z"},
    }
    store.put_evidence(original_rec)
    store.save_workflow(wf)

    # Initial check: pending = 1, resolved = 0
    resp1 = client.get("/api/review", headers={"X-Org-Id": org})
    assert resp1.json()["pending_count"] == 1
    assert resp1.json()["resolved_count"] == 0

    # Apply override via /api/workflows/{wf_id}/override
    ov_resp = client.post(
        f"/api/workflows/{wf_id}/override",
        headers={"X-Org-Id": org},
        json={
            "stage": "pack",
            "verdict": "PASS",
            "reason": "Manual operator visual inspection confirmed item identity",
            "operator": "alice",
        },
    )
    assert ov_resp.status_code == 200, ov_resp.text
    ov_wf = ov_resp.json()
    assert len(ov_wf.get("overrides", [])) == 1
    assert ov_wf["overrides"][0]["new_verdict"] == "PASS"

    # Second check: pending = 0, resolved = 1
    resp2 = client.get("/api/review", headers={"X-Org-Id": org})
    res_data = resp2.json()
    assert res_data["pending_count"] == 0
    assert res_data["resolved_count"] == 1

    resolved_item = res_data["resolved"][0]
    assert resolved_item["unit_id"] == unit_id
    assert resolved_item["has_override"] is True
    assert resolved_item["override"]["new_verdict"] == "PASS"
    assert resolved_item["effective_verdict"] == "PASS"

    # IMMUTABILITY CHECK: Original evidence record MUST NOT be modified or deleted
    persisted_original_ev = store.get_evidence(rec_id)
    assert persisted_original_ev is not None
    assert persisted_original_ev["decision"]["verdict"] == "UNCERTAIN"
    assert persisted_original_ev["decision"]["needs_human"] is True


def test_review_queue_tenant_isolation(tmp_path, monkeypatch):
    store = FileStore(tmp_path / "store")
    monkeypatch.setattr(api_mod, "STORE", store)
    client = TestClient(api_mod.app)

    # Create item for org_demo_alpha
    store.put_evidence({
        "record_id": "ev-alpha",
        "workflow_id": "wf-alpha",
        "stage": "prep",
        "subject": {"unit_id": "UNIT-ALPHA", "subject_id": "UNIT-ALPHA", "org_id": "org_demo_alpha"},
        "decision": {"verdict": "UNCERTAIN", "reason": "Alpha uncertain", "needs_human": True},
    })
    store.save_workflow({
        "schema_version": "1.0",
        "workflow_id": "wf-alpha",
        "unit_id": "UNIT-ALPHA",
        "subject_id": "UNIT-ALPHA",
        "org_id": "org_demo_alpha",
        "status": "BLOCKED",
        "stage_results": [{"stage": "prep", "record_id": "ev-alpha", "verdict": "UNCERTAIN", "needs_human": True}],
        "evidence_references": ["ev-alpha"],
        "transitions": [],
        "overrides": [],
        "errors": [],
        "timestamps": {"created_at": "2026-10-10T10:00:00Z", "updated_at": "2026-10-10T10:00:00Z"},
    })

    # Create item for org_demo_bravo
    store.put_evidence({
        "record_id": "ev-bravo",
        "workflow_id": "wf-bravo",
        "stage": "returns",
        "subject": {"unit_id": "UNIT-BRAVO", "subject_id": "UNIT-BRAVO", "org_id": "org_demo_bravo"},
        "decision": {"verdict": "UNCERTAIN", "reason": "Bravo uncertain", "needs_human": True},
    })
    store.save_workflow({
        "schema_version": "1.0",
        "workflow_id": "wf-bravo",
        "unit_id": "UNIT-BRAVO",
        "subject_id": "UNIT-BRAVO",
        "org_id": "org_demo_bravo",
        "status": "BLOCKED",
        "stage_results": [{"stage": "returns", "record_id": "ev-bravo", "verdict": "UNCERTAIN", "needs_human": True}],
        "evidence_references": ["ev-bravo"],
        "transitions": [],
        "overrides": [],
        "errors": [],
        "timestamps": {"created_at": "2026-10-10T10:00:00Z", "updated_at": "2026-10-10T10:00:00Z"},
    })

    # Alpha query
    r_alpha = client.get("/api/review", headers={"X-Org-Id": "org_demo_alpha"}).json()
    assert r_alpha["pending_count"] == 1
    assert r_alpha["pending"][0]["unit_id"] == "UNIT-ALPHA"

    # Bravo query
    r_bravo = client.get("/api/review", headers={"X-Org-Id": "org_demo_bravo"}).json()
    assert r_bravo["pending_count"] == 1
    assert r_bravo["pending"][0]["unit_id"] == "UNIT-BRAVO"


def test_clean_completed_workflows_omitted_from_review(tmp_path, monkeypatch):
    store = FileStore(tmp_path / "store")
    monkeypatch.setattr(api_mod, "STORE", store)
    client = TestClient(api_mod.app)

    org = "org_demo_alpha"
    store.put_evidence({
        "record_id": "ev-clean",
        "workflow_id": "wf-clean",
        "stage": "pack",
        "subject": {"unit_id": "UNIT-CLEAN", "subject_id": "UNIT-CLEAN", "org_id": org},
        "decision": {"verdict": "PASS", "reason": "All checks passed", "needs_human": False},
    })
    store.save_workflow({
        "schema_version": "1.0",
        "workflow_id": "wf-clean",
        "unit_id": "UNIT-CLEAN",
        "subject_id": "UNIT-CLEAN",
        "org_id": org,
        "status": "COMPLETED",
        "stage_results": [{"stage": "pack", "record_id": "ev-clean", "verdict": "PASS", "needs_human": False}],
        "evidence_references": ["ev-clean"],
        "transitions": [],
        "overrides": [],
        "errors": [],
        "timestamps": {"created_at": "2026-10-10T10:00:00Z", "updated_at": "2026-10-10T10:00:00Z"},
    })

    resp = client.get("/api/review", headers={"X-Org-Id": org}).json()
    assert resp["pending_count"] == 0
    assert resp["resolved_count"] == 0
