"""Optional HTTP front door for the orchestrator (useful for a deployed demo).

  uvicorn orchestration.api:app --port 8100
  POST /workflows                 {"org_id": "org_demo_alpha", "unit_id": "UNIT-0002"}   -> Workflow State (runs it)
  GET  /workflows/{id}            -> Workflow State
  GET  /workflows/{id}/evidence   -> the workflow plus all its evidence records
  POST /workflows/{id}/resume     -> continue after a halt / decision / failure
  POST /workflows/{id}/overrides  {"record_id": "...", "new_verdict": "PASS", "actor": "...", "reason": "..."}
  GET  /health                    -> orchestrator and every agent in the flow
Every /workflows/{id} route is tenant-scoped: send the caller's org as the `X-Org-Id` header (or `?org_id=`).
Another org's workflow answers 404, exactly like a workflow that does not exist (no existence oracle).
No authentication is included: X-Org-Id is a scoping key, not a credential. Add auth before you deploy publicly.
"""
from __future__ import annotations

import os
import re

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.utils import sample_data

from .clients import HttpClient, client_for, load_manifest
from .orchestrator import apply_override, bundle, default_flow_path, flow_stages, load_flow, resume, run_workflow
from .store import EvidenceConflict, FileStore, TenantViolation, WorkflowBusy

app = FastAPI(title="CUBE Round 3 orchestrator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(WorkflowBusy)
def _busy(request: Request, exc: WorkflowBusy) -> JSONResponse:
    """Another caller is advancing this workflow for longer than ORCH_LOCK_TIMEOUT_S (D-115). Nothing changed."""
    return JSONResponse(status_code=409, content={"detail": f"{exc}; nothing was changed, retry later"})
FLOW = os.environ.get("ORCH_FLOW") or default_flow_path()
STORE = FileStore()
ORG_ID = re.compile(r"^[A-Za-z0-9_]+$")
SUBJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@app.get("/health")
def health() -> dict:
    agents = {}
    for stage in flow_stages(load_flow(FLOW)):
        client = client_for(stage)
        try:
            agents[stage] = client.health() if isinstance(client, HttpClient) else {"status": "ok", "mode": "inproc"}
        except Exception as exc:
            agents[stage] = {"status": "down", "error": str(exc)[:200], "owner": load_manifest(stage)["owner"]}
    ok = all(a["status"] == "ok" for a in agents.values())
    return {"status": "ok" if ok else "degraded", "flow": load_flow(FLOW)["flow_id"], "agents": agents}


@app.post("/workflows")
def create(body: dict) -> dict:
    org, subject = body.get("org_id"), body.get("subject_id") or body.get("unit_id")
    if not org or not subject:
        raise HTTPException(422, "org_id and unit_id (or subject_id) are required")
    # D-114: workflow ids are "WF-<org>-<subject>". An org id containing "-" (or a path-like id) could claim another
    # tenant's workflow id, e.g. org "a-UNIT" + unit "1" == org "a" + unit "UNIT-1". Refuse instead of guessing.
    if not ORG_ID.match(str(org)) or not SUBJECT_ID.match(str(subject)) or ".." in str(subject):
        raise HTTPException(422, "org_id must match [A-Za-z0-9_]+ and unit_id [A-Za-z0-9][A-Za-z0-9_.-]*")
    case = {"org_id": org, "unit_id": subject, "route": body.get("route") or sample_data.route(subject, org),
            "returned": body.get("returned", sample_data.has("returns", subject, org))}
    return run_workflow(case, load_flow(FLOW), STORE)


def _org(x_org_id: str | None, org_id: str | None) -> str:
    org = x_org_id or org_id
    if not org:
        raise HTTPException(422, "tenant required: send the X-Org-Id header (or ?org_id=)")
    return org


def _get(workflow_id: str, org: str) -> dict:
    try:
        wf = STORE.load_workflow(workflow_id, org)
    except TenantViolation:
        wf = None  # same answer as "does not exist": never confirm another tenant's workflow exists
    if wf is None:
        raise HTTPException(404, f"no workflow {workflow_id}")
    return wf


@app.get("/workflows/{workflow_id}")
def get(workflow_id: str, x_org_id: str | None = Header(None), org_id: str | None = Query(None)) -> dict:
    return _get(workflow_id, _org(x_org_id, org_id))


@app.get("/workflows/{workflow_id}/evidence")
def evidence(workflow_id: str, x_org_id: str | None = Header(None), org_id: str | None = Query(None)) -> dict:
    return bundle(_get(workflow_id, _org(x_org_id, org_id)), STORE)


@app.post("/workflows/{workflow_id}/resume")
def resume_workflow(workflow_id: str, x_org_id: str | None = Header(None), org_id: str | None = Query(None)) -> dict:
    org = _org(x_org_id, org_id)
    _get(workflow_id, org)
    return resume(workflow_id, load_flow(FLOW), STORE, org_id=org)


@app.post("/workflows/{workflow_id}/overrides")
def override(workflow_id: str, body: dict, x_org_id: str | None = Header(None), org_id: str | None = Query(None)) -> dict:
    org = _org(x_org_id, org_id)
    _get(workflow_id, org)
    try:
        return apply_override(workflow_id, STORE, record_id=body.get("record_id", ""), new_verdict=body.get("new_verdict", ""),
                              actor=body.get("actor", ""), reason=body.get("reason", ""), new_outcome=body.get("new_outcome"),
                              org_id=org)
    except (ValueError, EvidenceConflict) as exc:
        raise HTTPException(422, str(exc)) from exc
