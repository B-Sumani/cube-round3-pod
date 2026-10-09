"""Tenant isolation is enforced by the STORE and the API, not only by the orchestrator's output validation.

One org must never read, overwrite or resume another org's workflow or evidence, whichever layer is asked.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from orchestration.orchestrator import apply_override, bundle, resume, run_workflow
from orchestration.store import FileStore, MemoryStore, TenantViolation
from shared.utils.hashing import seal

ALPHA, BRAVO = "org_demo_alpha", "org_demo_bravo"


def _alpha_workflow(cases, store):
    case = next(c for c in cases if c["org_id"] == ALPHA)
    return run_workflow(case, store=store)


@pytest.fixture(params=["memory", "file"])
def store(request, tmp_path):
    return MemoryStore() if request.param == "memory" else FileStore(tmp_path)


def test_owner_can_read_its_own_workflow_and_evidence(store, cases):
    wf = _alpha_workflow(cases, store)
    assert store.load_workflow(wf["workflow_id"], ALPHA)["workflow_id"] == wf["workflow_id"]
    for rid in wf["evidence_references"]:
        assert store.get_evidence(rid, ALPHA)["subject"]["org_id"] == ALPHA


def test_other_org_cannot_read_workflow_or_evidence(store, cases):
    wf = _alpha_workflow(cases, store)
    with pytest.raises(TenantViolation):
        store.load_workflow(wf["workflow_id"], BRAVO)
    for rid in wf["evidence_references"]:
        with pytest.raises(TenantViolation):
            store.get_evidence(rid, BRAVO)


def test_foreign_org_evidence_cannot_be_written_into_another_tenant(store, cases):
    wf = _alpha_workflow(cases, store)
    alpha_rec = store.get_evidence(wf["evidence_references"][0], ALPHA)
    # 1) a record about BRAVO, written in ALPHA's scope, is refused
    bravo_rec = seal({**alpha_rec, "record_id": "RCV-FOREIGN-1", "subject": {**alpha_rec["subject"], "org_id": BRAVO}})
    with pytest.raises(TenantViolation):
        store.put_evidence(bravo_rec, ALPHA)
    assert store.get_evidence("RCV-FOREIGN-1") is None
    # 2) BRAVO cannot claim an id ALPHA already owns, even with an unscoped write
    hijack = seal({**alpha_rec, "subject": {**alpha_rec["subject"], "org_id": BRAVO}})
    with pytest.raises(TenantViolation):
        store.put_evidence(hijack)
    assert store.get_evidence(alpha_rec["record_id"], ALPHA) == alpha_rec, "the owner's record is untouched"


def test_other_org_cannot_overwrite_a_workflow(store, cases):
    wf = _alpha_workflow(cases, store)
    with pytest.raises(TenantViolation):
        store.save_workflow({**wf, "org_id": BRAVO})
    with pytest.raises(TenantViolation):
        store.save_workflow(wf, BRAVO)
    assert store.load_workflow(wf["workflow_id"], ALPHA)["org_id"] == ALPHA


def test_orchestrator_resume_and_override_are_tenant_scoped(store, cases):
    wf = _alpha_workflow(cases, store)
    with pytest.raises(TenantViolation):
        resume(wf["workflow_id"], store=store, org_id=BRAVO)
    with pytest.raises(TenantViolation):
        apply_override(wf["workflow_id"], store, record_id=wf["evidence_references"][0], new_verdict="PASS",
                       actor="intruder", reason="cross-tenant", org_id=BRAVO)
    assert store.load_workflow(wf["workflow_id"], ALPHA)["overrides"] == []
    assert bundle(wf, store)["evidence"].keys() == set(wf["evidence_references"])


def test_file_store_refuses_path_like_ids(tmp_path):
    store = FileStore(tmp_path)
    for bad in ("../escape", "a/b", "a\\b", "C:evil"):
        with pytest.raises(ValueError):
            store.get_evidence(bad)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("OUT_DIR", str(tmp_path))
    import orchestration.api as mod
    mod = importlib.reload(mod)  # fresh FileStore under tmp_path
    return TestClient(mod.app)


def test_api_scopes_every_workflow_route_by_org(api, cases):
    case = next(c for c in cases if c["org_id"] == ALPHA)
    wf = api.post("/workflows", json={"org_id": ALPHA, "unit_id": case["unit_id"]}).json()
    wid, rid = wf["workflow_id"], wf["evidence_references"][0]

    assert api.get(f"/workflows/{wid}", headers={"X-Org-Id": ALPHA}).status_code == 200
    assert api.get(f"/workflows/{wid}?org_id={ALPHA}").status_code == 200
    assert api.get(f"/workflows/{wid}").status_code == 422, "no tenant, no answer"

    wrong = {"X-Org-Id": BRAVO}
    missing = api.get("/workflows/WF-nope", headers=wrong)
    for resp in (api.get(f"/workflows/{wid}", headers=wrong),
                 api.get(f"/workflows/{wid}/evidence", headers=wrong),
                 api.post(f"/workflows/{wid}/resume", headers=wrong),
                 api.post(f"/workflows/{wid}/overrides", headers=wrong,
                          json={"record_id": rid, "new_verdict": "PASS", "actor": "x", "reason": "y"})):
        assert resp.status_code == 404
        assert resp.json()["detail"] == f"no workflow {wid}", "indistinguishable from a missing workflow"
    assert missing.status_code == 404
    assert api.get(f"/workflows/{wid}", headers={"X-Org-Id": ALPHA}).json()["overrides"] == []
