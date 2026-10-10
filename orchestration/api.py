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

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from fastapi import APIRouter, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.utils import sample_data
from shared.utils.records import pending_output

from .clients import AgentRejected, AgentUnavailable, HttpClient, client_for, load_manifest
from .orchestrator import apply_override, bundle, default_flow_path, flow_stages, load_flow, resume, run_workflow, _validate
from .store import EvidenceConflict, FileStore, TenantViolation, WorkflowBusy

# Ensure in-process agents are used by default (e.g. for Vercel and local dev)
os.environ.setdefault("ORCH_MODE", "inproc")

FLOW = os.environ.get("ORCH_FLOW") or default_flow_path()
STORE = FileStore()
ORG_ID = re.compile(r"^[A-Za-z0-9_]+$")
SUBJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def seed_sample_workflows_if_empty(store: FileStore | None = None, flow_path: str | Path | None = None) -> None:
    """Seed sample workflows into the store if it contains no workflows yet."""
    target_store = store or STORE
    if not hasattr(target_store, "root"):
        return
    workflows_dir = target_store.root / "workflows"
    if not workflows_dir.exists() or not any(workflows_dir.glob("*.json")):
        cases_file = Path(__file__).resolve().parents[1] / "data" / "sample" / "cases.json"
        if cases_file.exists():
            try:
                cases = json.loads(cases_file.read_text(encoding="utf-8"))
                flow = load_flow(flow_path or FLOW)
                for case in cases:
                    run_workflow(case, flow, target_store)
            except Exception:
                pass


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed on startup if store is empty (e.g. fresh Vercel /tmp instance)
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        seed_sample_workflows_if_empty(STORE, FLOW)
    yield


# Immediate seed on module load if running under Vercel serverless environment
if os.environ.get("VERCEL") and not os.environ.get("PYTEST_CURRENT_TEST"):
    seed_sample_workflows_if_empty(STORE, FLOW)

app = FastAPI(title="CUBE Round 3 orchestrator", lifespan=lifespan)
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


router = APIRouter()


@router.get("/health")
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


@router.post("/workflows")
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
    if body.get("order_lines"):
        case["order_lines"] = str(body["order_lines"]).strip()
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


@router.get("/workflows/{workflow_id}")
def get(workflow_id: str, x_org_id: str | None = Header(None), org_id: str | None = Query(None)) -> dict:
    return _get(workflow_id, _org(x_org_id, org_id))


@router.get("/workflows/{workflow_id}/evidence")
def evidence(workflow_id: str, x_org_id: str | None = Header(None), org_id: str | None = Query(None)) -> dict:
    return bundle(_get(workflow_id, _org(x_org_id, org_id)), STORE)


@router.post("/workflows/{workflow_id}/resume")
def resume_workflow(workflow_id: str, x_org_id: str | None = Header(None), org_id: str | None = Query(None)) -> dict:
    org = _org(x_org_id, org_id)
    _get(workflow_id, org)
    return resume(workflow_id, load_flow(FLOW), STORE, org_id=org)


@router.post("/workflows/{workflow_id}/overrides")
def override(workflow_id: str, body: dict, x_org_id: str | None = Header(None), org_id: str | None = Query(None)) -> dict:
    org = _org(x_org_id, org_id)
    _get(workflow_id, org)
    try:
        return apply_override(workflow_id, STORE, record_id=body.get("record_id", ""), new_verdict=body.get("new_verdict", ""),
                              actor=body.get("actor", ""), reason=body.get("reason", ""), new_outcome=body.get("new_outcome"),
                              org_id=org)
    except (ValueError, EvidenceConflict) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/catalogue")
def catalogue_endpoint(x_org_id: str | None = Header(None), org_id: str | None = Query(None)) -> list[dict]:
    org = _org(x_org_id, org_id)
    # Tenancy check: verify org is authorized
    try:
        from agents.pack.catalogue import get_dev_catalogue
        cat_map = get_dev_catalogue(org)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    cat_csv = Path(__file__).resolve().parents[1] / "agents" / "pack" / "data" / "catalogue.csv"
    rows = []
    if cat_csv.is_file():
        import csv
        with open(cat_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sku = (r.get("sku") or "").strip()
                title = (r.get("title") or "").strip()
                desc = (r.get("description") or "").strip()
                pkg = r.get("expected_packaging") or r.get("packaging") or (
                    "bottle" if "bottle" in desc.lower() else ("box" if "box" in desc.lower() or "carton" in desc.lower() else "polybag" if "bag" in desc.lower() else "standard")
                )
                barcode = r.get("barcode") or f"BAR-{sku}"
                hazmat = "hazmat" in desc.lower() or "sanitizer" in desc.lower() or "acid" in desc.lower()
                rows.append({
                    "sku": sku,
                    "name": title,
                    "title": title,
                    "description": desc,
                    "expected_packaging": pkg,
                    "packaging_type": pkg,
                    "barcode": barcode,
                    "hazmat": hazmat,
                })
    else:
        for sku, info in cat_map.items():
            title = info.get("title", "")
            desc = info.get("description", "")
            pkg = "bottle" if "bottle" in desc.lower() else ("box" if "box" in desc.lower() or "carton" in desc.lower() else "standard")
            rows.append({
                "sku": sku,
                "name": title,
                "title": title,
                "description": desc,
                "expected_packaging": pkg,
                "packaging_type": pkg,
                "barcode": f"BAR-{sku}",
                "hazmat": "hazmat" in desc.lower() or "sanitizer" in desc.lower() or "acid" in desc.lower(),
            })
    return rows


MAX_UPLOAD_BYTES = int(4.5 * 1024 * 1024)
MAX_TOTAL_BYTES = MAX_UPLOAD_BYTES
MAX_FILE_BYTES = 4 * 1024 * 1024
ALLOWED_UPLOAD_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg", "application/octet-stream"}


def _resolve_upload_dir() -> Path:
    env_dir = os.environ.get("UPLOAD_DIR")
    if env_dir:
        d = Path(env_dir).resolve()
    else:
        tmp = Path("/tmp") if Path("/tmp").is_dir() else Path(tempfile.gettempdir())
        d = (tmp / "cube_uploads").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _normalize_order_lines(raw: str | None) -> str:
    """Normalizes order lines from JSON list/dict or delimited string into a standard string."""
    if not raw or not raw.strip():
        return ""
    text = raw.strip()
    if (text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}")):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                parts = []
                for item in parsed:
                    if isinstance(item, dict):
                        sku = item.get("sku") or item.get("product_id") or item.get("id")
                        qty = item.get("qty") or item.get("quantity") or 1
                        if sku:
                            parts.append(f"{sku}:{qty}")
                    elif isinstance(item, str):
                        parts.append(item)
                return ", ".join(parts)
            elif isinstance(parsed, dict):
                return ", ".join(f"{k}:{v}" for k, v in parsed.items())
        except Exception:
            pass
    return text


@router.post("/stages/{stage}/run-upload")
async def run_upload_endpoint(
    stage: str,
    file: list[UploadFile] = File(default=[]),
    files: list[UploadFile] = File(default=[]),
    unit_id: str | None = Form(None),
    unit_id_query: str | None = Query(None, alias="unit_id"),
    order_id: str | None = Form(None),
    order_id_query: str | None = Query(None, alias="order_id"),
    org_id: str | None = Form(None),
    org_id_query: str | None = Query(None, alias="org_id"),
    x_org_id: str | None = Header(None),
    order_lines: str | None = Form(None),
    order_lines_query: str | None = Query(None, alias="order_lines"),
    route: str | None = Form(None),
    channel: str | None = Form(None),
) -> dict:
    target_unit = unit_id or unit_id_query
    if not target_unit:
        raise HTTPException(422, "unit_id is required")

    org = _org(x_org_id, org_id or org_id_query)
    if not ORG_ID.match(str(org)) or not SUBJECT_ID.match(str(target_unit)) or ".." in str(target_unit):
        raise HTTPException(422, "org_id must match [A-Za-z0-9_]+ and unit_id [A-Za-z0-9][A-Za-z0-9_.-]*")

    # Validate stage
    valid_stages = {"receiving", "prep", "pack", "returns", "recovery"}
    if stage not in valid_stages:
        raise HTTPException(404, f"Unknown stage: {stage}")

    # Gather all uploaded files (from single 'file' or multiple 'files' / 'file' inputs)
    all_uploads = [f for f in (file + files) if f and f.filename]
    if len(all_uploads) == 0:
        raise HTTPException(422, "At least 1 photograph is required")
    if len(all_uploads) > 5:
        raise HTTPException(422, f"Maximum 5 photographs allowed (received {len(all_uploads)})")

    # Tenancy check: refuse cross-tenant requests
    if stage == "pack":
        from agents.pack.engine import is_dev_unit_under_other_org
        if is_dev_unit_under_other_org(org, target_unit):
            raise HTTPException(404, f"Unit {target_unit} not found for organisation {org}")
        if not sample_data.has("pack", target_unit, org):
            for other_org in ("org_demo_alpha", "org_demo_bravo"):
                if other_org != org and sample_data.has("pack", target_unit, other_org):
                    raise HTTPException(404, f"Unit {target_unit} not found for organisation {org}")
    else:
        for other_org in ("org_demo_alpha", "org_demo_bravo"):
            if other_org != org and sample_data.has(stage, target_unit, other_org):
                if not sample_data.has(stage, target_unit, org):
                    raise HTTPException(404, f"Unit {target_unit} not found for organisation {org}")

    upload_dir = _resolve_upload_dir()
    inputs = []
    total_bytes = 0

    for upload_f in all_uploads:
        ext = Path(upload_f.filename or "").suffix.lower()
        ct = (upload_f.content_type or "").lower()
        if ext not in ALLOWED_UPLOAD_EXTS and ct not in ALLOWED_MIME_TYPES:
            raise HTTPException(422, f"Unsupported file type '{ext or ct}'. Allowed formats: jpg, jpeg, png, webp")
        if ext and ext not in ALLOWED_UPLOAD_EXTS:
            raise HTTPException(422, f"Unsupported file extension '{ext}'. Allowed formats: jpg, jpeg, png, webp")

        raw_bytes = await upload_f.read()
        if len(raw_bytes) > MAX_FILE_BYTES:
            raise HTTPException(413, f"File too large: '{upload_f.filename}' exceeds 4 MB limit ({len(raw_bytes)} bytes)")
        total_bytes += len(raw_bytes)
        if total_bytes > MAX_TOTAL_BYTES:
            raise HTTPException(413, f"Total payload size ({total_bytes} bytes) exceeds 4.5 MB limit")

        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if ext not in ALLOWED_UPLOAD_EXTS:
            ext = ".png" if ct == "image/png" else (".webp" if ct == "image/webp" else ".jpg")
        dest_filename = f"{sha256}{ext}"
        dest_path = upload_dir / dest_filename
        dest_path.write_bytes(raw_bytes)
        ref = f"uploads/{dest_filename}"
        inputs.append({
            "ref": ref,
            "kind": "image",
            "sha256": sha256,
        })

    # Build agent input
    effective_order_lines = _normalize_order_lines(order_lines or order_lines_query)
    target_order_id = (order_id or order_id_query or "").strip()
    effective_route = route or ("mfn" if stage == "pack" else sample_data.route(target_unit, org))
    agent_input = {
        "schema_version": "1.0",
        "request_id": f"upload-{stage}-{target_unit}-{inputs[0]['sha256'][:8]}",
        "workflow_id": f"WF-{org}-{target_unit}",
        "stage": stage,
        "subject": {
            "org_id": org,
            "subject_id": target_unit,
            "route": effective_route,
        },
        "inputs": inputs,
        "previous_evidence": [],
        "context": {
            "overrides": [],
            "case": {
                "org_id": org,
                "unit_id": target_unit,
                "route": effective_route,
                "ad_hoc_upload": True,
                **({"order_id": target_order_id} if target_order_id else {}),
                **({"order_lines": effective_order_lines} if effective_order_lines else {}),
            },
            "ad_hoc_upload": True,
            "run_type": "ad_hoc_upload",
            **({"order_id": target_order_id} if target_order_id else {}),
            **({"order_lines": effective_order_lines} if effective_order_lines else {}),
        },
    }

    # Run agent through orchestrator client
    client = client_for(stage)
    manifest = load_manifest(stage)
    agent_id = manifest.get("agent_id", f"{stage}-agent")

    out = None
    try:
        out = client.run(agent_input, 30.0)
    except AgentRejected as exc:
        raise HTTPException(404, f"Agent refused request: {exc}") from exc
    except AgentUnavailable as exc:
        out = pending_output(agent_input, code="agent_unavailable", message=str(exc), retryable=True, agent_id=agent_id)
    except Exception as exc:
        out = pending_output(agent_input, code="agent_exception", message=f"{type(exc).__name__}: {exc}", retryable=False, agent_id=agent_id)

    # Validate output
    wf_stub = {"workflow_id": f"WF-{org}-{target_unit}", "org_id": org, "subject_id": target_unit}
    bad = _validate(out, wf_stub, stage)
    if bad:
        out = pending_output(agent_input, code="invalid_output", message="; ".join(bad), retryable=False, agent_id=agent_id)

    ev = out["evidence"]
    if isinstance(ev.get("payload"), dict):
        ev["payload"]["ad_hoc_upload"] = True
    try:
        STORE.put_evidence(ev, org)
    except Exception:
        pass

    stage_result = {
        "stage": stage,
        "agent_id": ev["agent_id"],
        "state": "completed" if ev["status"] == "completed" else "error",
        "verdict": ev["decision"]["verdict"],
        "outcome": ev["decision"]["outcome"],
        "needs_human": ev["decision"].get("needs_human"),
        "record_id": ev["record_id"],
        "evidence_status": ev["status"],
        "error": ev.get("error"),
        "next_step_recommendation": out.get("next_step_recommendation"),
        "runs": 1,
        "attempts": 1,
        "started_at": ev.get("captured_at"),
        "finished_at": ev.get("produced_at"),
    }
    wf = {
        "workflow_id": f"WF-{org}-{target_unit}",
        "org_id": org,
        "subject_id": target_unit,
        "status": "COMPLETED" if ev["status"] == "completed" else "FAILED",
        "stage_results": [stage_result],
        "evidence_references": [ev["record_id"]],
        "is_ad_hoc_upload": True,
    }
    return {
        "workflow": wf,
        "stage_result": stage_result,
        "evidence": ev,
        "output": out,
        "is_ad_hoc_upload": True,
        "storage_note": "Uploaded images are stored in ephemeral storage and will disappear on container restart.",
    }


# Include routes at root and with /api prefix
app.include_router(router)
app.include_router(router, prefix="/api")
