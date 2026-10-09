"""Receiving Manager: Round 2 agent integrated into the Pod contract.

handle(agent_input) -> agent_output. The Round 2 code lives in agents/receiving/r2/ (see PROVENANCE.md); this file is
only the boundary: PO lookup (tenant-scoped), perception, Round 2 deterministic rules, Evidence Record.

Two perception modes, chosen per request and always stated in model.name and payload.perception:
  vision    image captures exist in request["inputs"] and RECEIVING_VISION=on with an API key: ONE batched model call
            per unit (Round 2 VisionService, blind to the PO), then the Round 2 rules compare readings with the PO.
  recorded  no usable captures (or vision off): the operator's recorded counts/observations for the PO line are run
            through the same Round 2 rules. No model call. Not perception: the record says so.
The verdict is never set by a model: Round 2's decision_engine decides every check deterministically.
Run:  uvicorn agents.receiving.app:app --port 8101
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from shared.utils import sample_data
from shared.utils.records import build_output, build_record, check, pending_output, utcnow
from shared.utils.server import make_app

from .r2 import decision_engine as rules
from .r2.models.inspection import ReceivingImage
from .r2.models.po import PurchaseOrder

STAGE = "receiving"
AGENT_ID = "receiving-r2@1.0"
RULES_VERSION = "r2-a45de41"  # Round 2 source commit of decision_engine.py / vision.py
PROMPT_VERSION = "r2-vision-v1"
ROOT = Path(__file__).resolve().parents[2]
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
# Round 2 check names -> Pod check_keys (README of this folder). NOT_REQUIRED checks are omitted, not passed.
R2_TO_POD = {"sku_check": "identity_match", "variant_check": "variant_match", "carton_check": "carton_count",
             "units_per_carton_check": "units_per_carton", "quantity_check": "quantity",
             "damage_check": "carton_damage", "component_check": "components"}
# Round 2 reason codes -> the contract's uncertain_reason enum (the Round 2 code stays in check.detail).
UNCERTAIN_REASON = {"NOT_OBSERVED": "insufficient_evidence", "LOW_VISIBILITY": "poor_image",
                    "VIEWS_DISAGREE": "conflicting_evidence", "READINGS_DISAGREE": "conflicting_evidence",
                    "PO_FIELD_MISSING": "other", "PO_INCONSISTENT": "other", "INVALID_READING": "insufficient_evidence"}


# ---------------------------------------------------------------- PO + inputs
def purchase_order(row: dict) -> PurchaseOrder:
    return PurchaseOrder(
        po_id=row["po_number"], sku=row["sku"], product_name=row["product_title"],
        expected_quantity=int(row["qty_ordered"]), variant=row["spec_variant"] or "n/a",
        units_per_carton=int(row["units_per_carton_ordered"]), expected_cartons=int(row["cartons_ordered"]),
        expected_components=[c for c in row["spec_components"].split(";") if c.strip()],
        unit_id=row["unit_id"], asin=row["asin"], po_line=row["po_line"])


def row_input(row: dict) -> dict:
    """The PO line / receipt row this record is based on, content-addressed."""
    digest = hashlib.sha256(json.dumps(row, sort_keys=True).encode("utf-8")).hexdigest()
    path = sample_data.data_dir() / sample_data.FILES["receiving"]
    try:
        ref = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:  # DATA_DIR outside the repo: never put a local absolute path in evidence
        ref = path.name
    return {"ref": f"{ref}#{row['record_id']}", "kind": "csv_row", "sha256": digest}


def image_inputs(request: dict) -> list[dict]:
    return [i for i in request.get("inputs", []) if i.get("kind") == "image"]


def vision_settings():
    key = os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    if os.environ.get("RECEIVING_VISION", "off").lower() != "on" or not key:
        return None
    return SimpleNamespace(api_key=key, demo_mode=False, ai_model=os.environ.get("RECEIVING_MODEL", "gpt-4o-mini"),
                           openai_base_url=os.environ.get("OPENAI_BASE_URL", ""),
                           ai_timeout_s=float(os.environ.get("AI_TIMEOUT_S", "20")))


# ---------------------------------------------------------------- Round 2 rules -> Pod checks
def pod_check(key: str, result: dict, *, expected, observed, refs: list[str], confidence: float | None = None,
              measurements: dict | None = None) -> dict | None:
    if result["status"] == "NOT_REQUIRED":
        return None
    detail = f"{result['reason']} [{result['reason_code']}]"
    if measurements:
        detail += f" readings={measurements.get('readings')}"
    return check(key, result["status"], confidence, expected=expected, observed=observed, detail=detail,
                 evidence_refs=refs, uncertain_reason=UNCERTAIN_REASON.get(result["reason_code"], "insufficient_evidence"))


def recorded_checks(row: dict, po: PurchaseOrder, refs: list[str]) -> tuple[list[dict], list[str]]:
    """Operator-recorded receipt -> Round 2 rules. Returns (checks, checks not performed and why)."""
    unseen = lambda v: None if (v or "").strip().lower() in rules.UNSEEN_MARKERS else v  # noqa: E731
    num = lambda v: int(v) if unseen(v) is not None else None  # noqa: E731
    cartons, per_carton, total = num(row["cartons_received"]), num(row["units_per_carton_counted"]), num(row["qty_received"])
    identity = (row["identity_match"] or "").strip().lower()
    identity_result = (
        rules._result("PASS", "Operator confirmed SKU/variant match the PO line.", "MATCH") if identity == "yes" else
        rules._result("FAIL", "Operator recorded that the received item does not match the PO line.", "IDENTITY_MISMATCH")
        if identity == "no" else rules._result("UNCERTAIN", "Identity was not confirmed.", "NOT_OBSERVED"))
    flags = [f for f in row["quality_flags"].split(";") if f]
    damage = lambda v: [] if (v or "").strip().lower() in rules.NO_DAMAGE_MARKERS else rules.normalize_damage(v)  # noqa: E731
    checks = [
        pod_check("identity_match", identity_result, expected=f"{po.sku} {po.variant}", observed=row["identity_match"], refs=refs),
        pod_check("carton_count", rules.evaluate_carton_check(po.expected_cartons, cartons),
                  expected=po.expected_cartons, observed=cartons, refs=refs),
        pod_check("units_per_carton", rules.evaluate_units_per_carton_check(po.units_per_carton, per_carton),
                  expected=po.units_per_carton, observed=per_carton, refs=refs),
        pod_check("quantity", rules.evaluate_total_quantity_check(po, total, cartons, per_carton),
                  expected=po.expected_quantity, observed=total, refs=refs),
        pod_check("carton_damage", rules.evaluate_damage_check(damage(row["carton_damage"])),
                  expected="none", observed=row["carton_damage"], refs=refs),
        pod_check("unit_damage", rules.evaluate_damage_check(damage(row["unit_damage"])),
                  expected="none", observed=row["unit_damage"], refs=refs),
        check("quality_flags", "FAIL" if flags else "PASS", None, expected=[], observed=flags, evidence_refs=refs,
              detail="operator quality flags on the receipt"),
    ]
    # Round 2 component_check needs per-component observations; the receipt only has a flag, so it is not run.
    return [c for c in checks if c], ["components: no per-component observation recorded (see quality_flags)"]


def vision_checks(request: dict, row: dict, po: PurchaseOrder, settings) -> tuple[list[dict], dict, list[str]]:
    """One batched model call over every image for this unit, then Round 2 fusion + rules."""
    from .r2.vision import VisionService

    root = Path(os.environ.get("INPUT_DIR", ROOT / "data" / "input"))
    images = []
    for item in image_inputs(request):
        path = (root / item["ref"]).resolve()
        if root.resolve() not in path.parents:  # path traversal: a ref must stay under the input root
            raise ValueError(f"input ref escapes the input root: {item['ref']}")
        images.append(ReceivingImage(image_id=item["ref"], inspection_id=request["workflow_id"], filename=path.name,
                                     stored_filename=path.name, image_path=str(path),
                                     image_type=path.stem.split("_")[-1], mime_type=MIME.get(path.suffix.lower(), "image/jpeg"),
                                     file_size=path.stat().st_size, sha256_digest=item.get("sha256") or ""))
    service = VisionService(SimpleNamespace(po=po, images=images))
    result = service.analyze(settings)
    evidence_by_id = {e["evidence_id"]: e["image_id"] for e in result["evidence"]}
    checks = []
    for c in result["checks"]:
        refs = sorted({evidence_by_id[i] for i in c["evidence_ids"] if i in evidence_by_id})
        made = pod_check(R2_TO_POD[c["check_name"]], {"status": c["status"], "reason": c["reason"], "reason_code": c["reason_code"]},
                         expected=c["expected_value"], observed=c["observed_value"], refs=refs,
                         confidence=c["confidence"], measurements=c["measurements"])
        if made:
            checks.append(made)
    model = {"name": settings.ai_model, "version": service.model_version, "provider": "openai",
             "prompt_version": PROMPT_VERSION, "calls": 1, "cost_usd": None}
    return checks, {"model": model, "usage": service.usage, "readings": result["evidence"]}, []


# ---------------------------------------------------------------- entry point
def handle(request: dict) -> dict:
    s = request["subject"]
    row = sample_data.row("receiving", s["subject_id"], s["org_id"])  # LookupError -> refused (tenancy), never answered
    po = purchase_order(row)
    photo_refs = [p for p in row["photo_refs"].split(";") if p]
    images, settings = image_inputs(request), vision_settings()
    record_id = f"RCV-{s['subject_id']}-{hashlib.sha256(request['request_id'].encode()).hexdigest()[:8]}"
    extra: dict = {}

    if images and settings:
        try:
            checks, extra, not_run = vision_checks(request, row, po, settings)
        except Exception as exc:  # fail open: a model/IO error is recorded as pending, never a verdict
            return pending_output(request, code="model_error", message=f"{type(exc).__name__}: {exc}"[:300],
                                  agent_id=AGENT_ID)
        perception, model, inputs = "vision", extra.pop("model"), [*images, row_input(row)]
    else:
        refs = [i["ref"] for i in images] or photo_refs
        checks, not_run = recorded_checks(row, po, refs)
        perception = "recorded"
        model = {"name": "receiving-r2-rules", "version": RULES_VERSION, "provider": None, "prompt_version": None,
                 "calls": 0, "cost_usd": 0}
        inputs = [*images, row_input(row)] if images else [row_input(row), *({"ref": p, "kind": "image"} for p in photo_refs)]

    verdict = rules.evaluate_overall([{"status": c["verdict"]} for c in checks])
    verdict = {"EXCEPTION": "FAIL"}.get(verdict, verdict)
    identity_failed = any(c["check_key"] == "identity_match" and c["verdict"] == "FAIL" for c in checks)
    outcome = {"PASS": "accept", "UNCERTAIN": "pending_review"}.get(verdict, "reject" if identity_failed else "accept_with_exceptions")
    failed = [c["check_key"] for c in checks if c["verdict"] == "FAIL"]
    unsure = [c["check_key"] for c in checks if c["verdict"] == "UNCERTAIN"]
    reason = (f"{perception}: " + (f"failed {', '.join(failed)}" if failed else "no failed checks")
              + (f"; uncertain {', '.join(unsure)}" if unsure else ""))
    qo = po.expected_quantity
    qr = next((c.get("observed") for c in checks if c["check_key"] == "quantity"), None)
    shortfall = max(qo - qr, 0) if isinstance(qr, int) else None
    record = build_record(
        request, agent_id=AGENT_ID, record_id=record_id, captured_at=row["captured_at"] or utcnow(),
        operator_id=row["operator_id"], unit_scope="po_line",  # Round 2 receiving rows are PO lines (finding F-08)
        refs={"po_number": row["po_number"], "po_line": row["po_line"], "sku": row["sku"], "asin": row["asin"]},
        checks=checks, verdict=verdict, outcome=outcome, model=model, inputs=inputs, reason=reason,
        payload={"perception": perception, "supplier": row["supplier"], "qty_ordered": qo, "qty_received": qr,
                 # supplier-side shortfall (finding F-10): NOT channel-side loss; Recovery must not claim it from the channel
                 "shortfall_units": shortfall, "shortfall_side": "supplier" if shortfall else None,
                 "quality_flags": [f for f in row["quality_flags"].split(";") if f],
                 "checks_not_performed": not_run, **extra},
    )
    return build_output(record)


app = make_app(STAGE, handle)
