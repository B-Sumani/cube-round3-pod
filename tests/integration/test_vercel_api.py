"""Tests verifying Vercel deployment paths, /api prefix, and storage configuration."""
import os
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

import orchestration.api as api_mod
from orchestration.store import FileStore


def test_api_prefix_health_and_root_health():
    client = TestClient(api_mod.app)
    # /api/health must respond
    r_api = client.get("/api/health")
    assert r_api.status_code == 200
    data_api = r_api.json()
    assert "status" in data_api and "agents" in data_api

    # /health must also respond
    r_root = client.get("/health")
    assert r_root.status_code == 200
    assert r_root.json() == data_api


def test_api_prefix_workflow_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "STORE", FileStore(tmp_path))
    client = TestClient(api_mod.app)

    # POST /api/workflows
    r = client.post("/api/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0001"})
    assert r.status_code == 200
    wf = r.json()
    assert wf["workflow_id"] == "WF-org_demo_alpha-UNIT-0001"

    # GET /api/workflows/{id}
    r_get = client.get(f"/api/workflows/{wf['workflow_id']}", headers={"X-Org-Id": "org_demo_alpha"})
    assert r_get.status_code == 200
    assert r_get.json()["workflow_id"] == wf["workflow_id"]

    # GET /api/workflows/{id}/evidence
    r_ev = client.get(f"/api/workflows/{wf['workflow_id']}/evidence", headers={"X-Org-Id": "org_demo_alpha"})
    assert r_ev.status_code == 200
    assert "evidence" in r_ev.json()


def test_filestore_defaults_to_tmp_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("OUT_DIR", raising=False)
    store = FileStore()
    assert str(store.root).replace("\\", "/").endswith("/tmp/cube-out")


def test_filestore_respects_custom_out_dir_on_vercel(monkeypatch, tmp_path):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "custom"))
    store = FileStore()
    assert store.root == tmp_path / "custom"


def test_seed_sample_workflows_populates_empty_store(tmp_path):
    store = FileStore(tmp_path)
    wf_dir = store.root / "workflows"
    assert not any(wf_dir.glob("*.json"))

    api_mod.seed_sample_workflows_if_empty(store)
    assert any(wf_dir.glob("*.json"))
    assert (wf_dir / "WF-org_demo_alpha-UNIT-0001.json").exists()
