"""Core execution pipeline for Pack Manager.

Implements Round 3 contract rules:
1. Tenancy: Validates org_id and subject. Rejects path traversal escaping INPUT_DIR.
   Raises LookupError on cross-tenant requests.
2. Deterministic record_id matching ^PCK-[A-Za-z0-9._-]+$ with deterministic content_hash.
3. Consumes only Receiving record IDs in upstream_refs and honors context.overrides.
4. If inputs contains real image captures, uses real vision pipeline.
   If inputs is empty and unit exists in sample data, falls back to sample replay.
5. All image inputs are checked: safe paths, read bytes, and SHA-256 integrity.
   Missing or mismatched images yield UNCERTAIN with zero model calls.
6. Single model call receives all validated images.
7. Missing order lines -> UNCERTAIN (insufficient_evidence).
8. captured_at resolved via: context -> EXIF -> file mtime (earliest across images).
9. Missing API key / model failure -> fail-open pending_output with code="model_error".
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import struct
from typing import Any, Dict, List, Optional, Tuple

from shared.utils import sample_data
from shared.utils.hashing import seal
from shared.utils.records import build_output, build_record, check as make_check, pending_output
from shared.utils.stubs import effective_verdict, photos

from agents.pack.catalogue import build_candidate_skus, get_org_catalogue
from agents.pack.config import DEFAULT_CONFIG, PackConfig
from agents.pack.evaluator import CheckResult, evaluate_pack_box, parse_order_lines
from agents.pack.mapping import map_outcome, map_uncertain_reason, map_verdict, to_contract_check
from agents.pack.model_adapter import (
    GeminiVisionAdapter,
    MockVisionAdapter,
    ModelError,
    ModelParsingError,
    ModelProviderError,
    ModelTimeoutError,
    VisionModelAdapter,
)
from agents.pack.parser import ImageQuality, ModelObservation, ObservedItem

STAGE = "pack"
AGENT_ID = "pack-manager@1.0.0"
ROOT_DIR = Path(__file__).resolve().parents[2]

# Injectable adapter for tests
_TEST_ADAPTER: Optional[VisionModelAdapter] = None


def set_test_adapter(adapter: Optional[VisionModelAdapter]) -> None:
    """Injects an adapter for testing (e.g. MockVisionAdapter)."""
    global _TEST_ADAPTER
    _TEST_ADAPTER = adapter


def get_active_adapter() -> VisionModelAdapter:
    """Returns the injected test adapter or instantiates a fresh GeminiVisionAdapter."""
    if _TEST_ADAPTER is not None:
        return _TEST_ADAPTER
    return GeminiVisionAdapter()


def _resolve_input_dir() -> Path:
    env_dir = os.environ.get("INPUT_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    return (ROOT_DIR / "data" / "input").resolve()


def _validate_safe_path(ref: str, input_dir: Path) -> Path:
    """Ensures input ref does not escape input_dir."""
    if ref.startswith("/") or ref.startswith("\\") or ":" in ref:
        raise LookupError(f"Absolute paths forbidden in ref: {ref}")
    target = (input_dir / ref).resolve()
    try:
        target.relative_to(input_dir)
    except ValueError as exc:
        raise LookupError(f"Path traversal detected in ref: {ref}") from exc
    return target


def _extract_exif_datetime(image_bytes: bytes) -> Optional[datetime]:
    """Extracts DateTimeOriginal (tag 0x9003) or DateTime (tag 0x0132) from JPEG EXIF header.

    Implemented using Python standard library struct with zero third-party dependencies.
    """
    if len(image_bytes) < 4 or image_bytes[:2] != b"\xff\xd8":
        return None
    idx = 2
    data_len = len(image_bytes)
    while idx < data_len - 4:
        if image_bytes[idx] != 0xFF:
            idx += 1
            continue
        marker = image_bytes[idx + 1]
        if marker in (0xD9, 0xDA):
            break
        if idx + 4 > data_len:
            break
        length = struct.unpack(">H", image_bytes[idx + 2 : idx + 4])[0]
        if marker == 0xE1:
            app1 = image_bytes[idx + 4 : idx + 2 + length]
            if app1.startswith(b"Exif\x00\x00"):
                tiff = app1[6:]
                if len(tiff) < 8:
                    return None
                endian = "<" if tiff[:2] == b"II" else (">" if tiff[:2] == b"MM" else None)
                if not endian:
                    return None
                first_ifd = struct.unpack(endian + "I", tiff[4:8])[0]

                def read_ifd(offset: int) -> Dict[int, Tuple[int, int, bytes]]:
                    if len(tiff) < offset + 2:
                        return {}
                    num = struct.unpack(endian + "H", tiff[offset : offset + 2])[0]
                    entries: Dict[int, Tuple[int, int, bytes]] = {}
                    pos = offset + 2
                    for _ in range(num):
                        if len(tiff) < pos + 12:
                            break
                        tag, ftype, count, val_or_off = struct.unpack(endian + "HHI4s", tiff[pos : pos + 12])
                        pos += 12
                        entries[tag] = (ftype, count, val_or_off)
                    return entries

                ifd0 = read_ifd(first_ifd)
                exif_ifd: Dict[int, Tuple[int, int, bytes]] = {}
                if 0x8769 in ifd0:
                    exif_off = struct.unpack(endian + "I", ifd0[0x8769][2])[0]
                    exif_ifd = read_ifd(exif_off)

                dto_entry = exif_ifd.get(0x9003) or ifd0.get(0x9003) or ifd0.get(0x0132)
                if dto_entry:
                    ftype, count, val_or_off = dto_entry
                    off = struct.unpack(endian + "I", val_or_off)[0]
                    if off + count <= len(tiff):
                        raw_str = tiff[off : off + count].decode("ascii", errors="ignore").strip("\x00 \r\n")
                        try:
                            dt = datetime.strptime(raw_str, "%Y:%m:%d %H:%M:%S")
                            return dt.replace(tzinfo=timezone.utc)
                        except Exception:
                            pass
                return None
        idx += 2 + length
    return None


def _resolve_context_captured_at(agent_input: dict) -> Optional[str]:
    """Resolves valid ISO 8601 capture time from agent_input context if present."""
    ctx = agent_input.get("context", {})
    candidates: List[Any] = []
    if isinstance(ctx, dict):
        if ctx.get("captured_at"):
            candidates.append(ctx["captured_at"])
        case_obj = ctx.get("case")
        if isinstance(case_obj, dict) and case_obj.get("captured_at"):
            candidates.append(case_obj["captured_at"])
    if agent_input.get("captured_at"):
        candidates.append(agent_input["captured_at"])

    for cand in candidates:
        if isinstance(cand, str) and cand.strip():
            try:
                dt = datetime.fromisoformat(cand.strip())
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                continue
    return None


def _resolve_captured_at(
    agent_input: dict,
    loaded_images: List[Dict[str, Any]],
    fallback_file_paths: Optional[List[Path]] = None,
) -> Tuple[str, str]:
    """Resolves (captured_at, captured_at_source) in strict order of priority:

    a) capture time in agent_input['context'] (e.g. context.case.captured_at or context.captured_at)
    b) image EXIF DateTimeOriginal (earliest among images)
    c) image file modified time (earliest among images)
    """
    # a) Context
    ctx_dt = _resolve_context_captured_at(agent_input)
    if ctx_dt:
        return ctx_dt, "context"

    # b) EXIF DateTimeOriginal
    exif_dates: List[datetime] = []
    for item in loaded_images:
        raw_bytes = item.get("bytes")
        if raw_bytes:
            exif_dt = _extract_exif_datetime(raw_bytes)
            if exif_dt:
                exif_dates.append(exif_dt)
    if exif_dates:
        earliest_exif = min(exif_dates)
        return earliest_exif.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "exif"

    # c) File modified time (mtime)
    paths: List[Path] = [item["file_path"] for item in loaded_images if item.get("file_path")]
    if not paths and fallback_file_paths:
        paths = [p for p in fallback_file_paths if p.is_file()]

    mtimes: List[datetime] = []
    for p in paths:
        try:
            mtime = p.stat().st_mtime
            dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            mtimes.append(dt)
        except Exception:
            continue

    if mtimes:
        earliest_mtime = min(mtimes)
        return earliest_mtime.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "file_mtime"

    # Fallback to current UTC clock (never a hardcoded fixed date)
    now_dt = datetime.now(timezone.utc)
    return now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "file_mtime"


def _resolve_order_lines(agent_input: dict, subject_id: str, org_id: str) -> Optional[str]:
    """Resolves order lines from context, document inputs, or sample data fallback."""
    ctx = agent_input.get("context", {})
    case_ctx = ctx.get("case", {})
    if isinstance(case_ctx, dict) and case_ctx.get("order_lines"):
        lines_val = case_ctx["order_lines"]
        if isinstance(lines_val, list):
            tokens = []
            for item in lines_val:
                if isinstance(item, dict) and "sku" in item:
                    tokens.append(f"{item['sku']}:{item.get('quantity', item.get('count', 1))}")
                else:
                    tokens.append(str(item))
            return ";".join(tokens)
        return str(lines_val).strip()

    if ctx.get("order_lines"):
        lines_val = ctx["order_lines"]
        if isinstance(lines_val, list):
            tokens = []
            for item in lines_val:
                if isinstance(item, dict) and "sku" in item:
                    tokens.append(f"{item['sku']}:{item.get('quantity', item.get('count', 1))}")
                else:
                    tokens.append(str(item))
            return ";".join(tokens)
        return str(lines_val).strip()

    # Check for document in inputs
    for inp in agent_input.get("inputs", []):
        if inp.get("kind") in ("document", "csv_row", "other") and "order" in inp.get("ref", "").lower():
            p = _resolve_input_dir() / inp["ref"]
            if p.is_file():
                return p.read_text(encoding="utf-8").strip()

    # Fallback to sample data if unit exists in pack_sample.csv
    if sample_data.has("pack", subject_id, org_id):
        return sample_data.row("pack", subject_id, org_id).get("order_lines", "").strip()

    return None


def run_pack_pipeline(
    agent_input: dict,
    config: Optional[PackConfig] = None,
    adapter: Optional[VisionModelAdapter] = None,
) -> dict:
    """Main execution pipeline for an Agent Input."""
    cfg = config or DEFAULT_CONFIG
    s = agent_input["subject"]
    org_id = s.get("org_id", "")
    subject_id = s.get("subject_id") or s.get("unit_id", "")

    # 1. Tenancy validation
    # Verify org catalogue is accessible (raises LookupError for unknown/unauthorized org)
    try:
        catalogue = get_org_catalogue(org_id)
    except LookupError as exc:
        raise LookupError(f"Tenancy rejection: {exc}") from exc

    # If subject exists only under another org in sample data, reject cross-tenant
    other_orgs = {"org_demo_alpha", "org_demo_bravo"} - {org_id}
    if not sample_data.has("pack", subject_id, org_id) and any(
        sample_data.has("pack", subject_id, other) for other in other_orgs
    ):
        raise LookupError(f"Tenancy violation: {subject_id} does not belong to {org_id}")

    # 2. Upstream evidence handling (Receiving only)
    receiving_records = [
        r for r in agent_input.get("previous_evidence", []) if r.get("stage") == "receiving"
    ]
    upstream_refs = [r["record_id"] for r in receiving_records]
    upstream_verdicts = {r["record_id"]: effective_verdict(agent_input, r) for r in receiving_records}

    # 3. Deterministic record_id & metadata
    clean_sub = re.sub(r"[^A-Za-z0-9._-]", "-", subject_id)
    if sample_data.has("pack", subject_id, org_id):
        sample_row = sample_data.row("pack", subject_id, org_id)
        record_id = sample_row["record_id"]
        operator_id = sample_row["operator_id"]
        order_id = sample_row["order_id"]
        channel = sample_row.get("channel", "mfn")
    else:
        record_id = f"PCK-{clean_sub}"
        operator_id = "op_pack_system"
        order_id = f"ORD-{clean_sub}"
        channel = "mfn"

    # 4. Resolve Order Lines
    order_lines = _resolve_order_lines(agent_input, subject_id, org_id)
    order_skus = list(parse_order_lines(order_lines).keys()) if order_lines else []
    candidate_skus = build_candidate_skus(org_id, order_skus)

    # 5. Determine inputs and execution path
    image_inputs = [
        inp for inp in agent_input.get("inputs", [])
        if inp.get("kind") == "image" or str(inp.get("ref", "")).lower().endswith((".jpg", ".jpeg", ".png"))
    ]

    # Path A: Real image inputs provided in agent_input["inputs"]
    if image_inputs:
        input_dir = _resolve_input_dir()

        # Validate safe path for ALL image inputs first (rejecting path traversal escaping INPUT_DIR)
        safe_paths: List[Path] = []
        for inp in image_inputs:
            ref = inp["ref"]
            safe_paths.append(_validate_safe_path(ref, input_dir))

        # Initial resolution of captured_at across existing image files or context
        captured_at, captured_at_source = _resolve_captured_at(
            agent_input, [], fallback_file_paths=safe_paths
        )

        loaded_images: List[Dict[str, Any]] = []
        for inp, file_path in zip(image_inputs, safe_paths):
            ref = inp["ref"]

            # 1. Missing file check
            if not file_path.is_file():
                checks = {
                    "items_present": CheckResult("UNCERTAIN", "FILE_NOT_FOUND", f"Image file missing on disk: {ref}"),
                    "quantities_correct": CheckResult("UNCERTAIN", "FILE_NOT_FOUND", f"Image file missing on disk: {ref}"),
                    "no_extra_items": CheckResult("UNCERTAIN", "FILE_NOT_FOUND", f"Image file missing on disk: {ref}"),
                }
                return _build_response_record(
                    agent_input=agent_input, record_id=record_id, captured_at=captured_at, operator_id=operator_id,
                    order_id=order_id, channel=channel, order_lines=order_lines or "", candidate_skus=candidate_skus,
                    checks=checks, verdict="UNCERTAIN", operator_action="STOP", upstream_refs=upstream_refs,
                    upstream_verdicts=upstream_verdicts, model_info={"name": "filesystem", "version": "1.0", "calls": 0},
                    source="missing_image_file", observation=None, evidence_refs=[ref],
                    captured_at_source=captured_at_source,
                    image_refs=[item.get("ref", "") for item in image_inputs],
                    image_sha256={},
                    offending_ref=ref,
                    error_detail=f"Image file missing on disk: {ref}",
                )

            # 2. Unreadable file check
            try:
                raw_bytes = file_path.read_bytes()
            except Exception as exc:
                checks = {
                    "items_present": CheckResult("UNCERTAIN", "FILE_NOT_FOUND", f"Image file unreadable on disk: {ref}"),
                    "quantities_correct": CheckResult("UNCERTAIN", "FILE_NOT_FOUND", f"Image file unreadable on disk: {ref}"),
                    "no_extra_items": CheckResult("UNCERTAIN", "FILE_NOT_FOUND", f"Image file unreadable on disk: {ref}"),
                }
                return _build_response_record(
                    agent_input=agent_input, record_id=record_id, captured_at=captured_at, operator_id=operator_id,
                    order_id=order_id, channel=channel, order_lines=order_lines or "", candidate_skus=candidate_skus,
                    checks=checks, verdict="UNCERTAIN", operator_action="STOP", upstream_refs=upstream_refs,
                    upstream_verdicts=upstream_verdicts, model_info={"name": "filesystem", "version": "1.0", "calls": 0},
                    source="unreadable_image_file", observation=None, evidence_refs=[ref],
                    captured_at_source=captured_at_source,
                    image_refs=[item.get("ref", "") for item in image_inputs],
                    image_sha256={},
                    offending_ref=ref,
                    error_detail=f"Image file unreadable on disk: {ref}: {exc}",
                )

            # 3. SHA-256 verification
            actual_sha = hashlib.sha256(raw_bytes).hexdigest()
            expected_sha = inp.get("sha256")
            if expected_sha and actual_sha.lower() != str(expected_sha).lower():
                checks = {
                    "items_present": CheckResult("UNCERTAIN", "SHA256_MISMATCH", f"Image SHA-256 mismatch for ref: {ref}"),
                    "quantities_correct": CheckResult("UNCERTAIN", "SHA256_MISMATCH", f"Image SHA-256 mismatch for ref: {ref}"),
                    "no_extra_items": CheckResult("UNCERTAIN", "SHA256_MISMATCH", f"Image SHA-256 mismatch for ref: {ref}"),
                }
                return _build_response_record(
                    agent_input=agent_input, record_id=record_id, captured_at=captured_at, operator_id=operator_id,
                    order_id=order_id, channel=channel, order_lines=order_lines or "", candidate_skus=candidate_skus,
                    checks=checks, verdict="UNCERTAIN", operator_action="STOP", upstream_refs=upstream_refs,
                    upstream_verdicts=upstream_verdicts, model_info={"name": "integrity_check", "version": "1.0", "calls": 0},
                    source="sha256_mismatch", observation=None, evidence_refs=[ref],
                    captured_at_source=captured_at_source,
                    image_refs=[item.get("ref", "") for item in image_inputs],
                    image_sha256={item["ref"]: item["sha256"] for item in loaded_images},
                    offending_ref=ref,
                    error_detail=f"SHA-256 mismatch for {ref}: expected {expected_sha}, got {actual_sha}",
                )

            loaded_images.append({
                "ref": ref,
                "bytes": raw_bytes,
                "sha256": actual_sha,
                "file_path": file_path,
            })

        # Re-resolve captured_at with all successfully loaded images (evaluates EXIF on all images)
        captured_at, captured_at_source = _resolve_captured_at(
            agent_input, loaded_images, fallback_file_paths=safe_paths
        )

        # Missing order lines check
        if not order_lines:
            checks = {
                "items_present": CheckResult("UNCERTAIN", "ORDER_LINES_MISSING", "Order lines not provided in context or case"),
                "quantities_correct": CheckResult("UNCERTAIN", "ORDER_LINES_MISSING", "Order lines not provided in context or case"),
                "no_extra_items": CheckResult("UNCERTAIN", "ORDER_LINES_MISSING", "Order lines not provided in context or case"),
            }
            return _build_response_record(
                agent_input=agent_input, record_id=record_id, captured_at=captured_at, operator_id=operator_id,
                order_id=order_id, channel=channel, order_lines="", candidate_skus=candidate_skus,
                checks=checks, verdict="UNCERTAIN", operator_action="STOP", upstream_refs=upstream_refs,
                upstream_verdicts=upstream_verdicts, model_info={"name": "order_check", "version": "1.0", "calls": 0},
                source="missing_order_lines", observation=None, evidence_refs=[it["ref"] for it in loaded_images],
                captured_at_source=captured_at_source,
                image_refs=[it["ref"] for it in loaded_images],
                image_sha256={it["ref"]: it["sha256"] for it in loaded_images},
            )

        # Call vision model adapter: EXACTLY ONE model call per unit with all images
        active_adapter = adapter or get_active_adapter()
        try:
            observation, latency_ms, model_info = active_adapter.analyze_box(
                images=[it["bytes"] for it in loaded_images],
                candidate_skus=candidate_skus,
                catalogue=catalogue,
                timeout_seconds=cfg.total_timeout_budget,
            )
        except (ModelProviderError, ModelTimeoutError, ModelParsingError, ModelError) as err:
            return pending_output(
                agent_input,
                code="model_error",
                message=str(err),
                retryable=False,
                agent_id=AGENT_ID,
            )

        checks_dict, verdict, operator_action = evaluate_pack_box(
            order_lines_str=order_lines,
            observation=observation,
            candidate_skus=candidate_skus,
            config=cfg,
        )

        return _build_response_record(
            agent_input=agent_input, record_id=record_id, captured_at=captured_at, operator_id=operator_id,
            order_id=order_id, channel=channel, order_lines=order_lines, candidate_skus=candidate_skus,
            checks=checks_dict, verdict=verdict, operator_action=operator_action, upstream_refs=upstream_refs,
            upstream_verdicts=upstream_verdicts, model_info=model_info, source="vision_pipeline",
            observation=observation, evidence_refs=[it["ref"] for it in loaded_images],
            captured_at_source=captured_at_source,
            image_refs=[it["ref"] for it in loaded_images],
            image_sha256={it["ref"]: it["sha256"] for it in loaded_images},
            latency_ms=latency_ms,
        )

    # Path B: Inputs is empty and unit exists in sample data -> sample replay fallback
    if sample_data.has("pack", subject_id, org_id):
        r = sample_data.row("pack", subject_id, org_id)
        refs = [p["ref"] for p in photos(r)]
        order_dict = parse_order_lines(r["order_lines"])
        observed_dict = parse_order_lines(r["observed_in_box"])

        obs_items = [
            ObservedItem(sku=k, count=v, count_confidence=1.0, identity_confidence=1.0)
            for k, v in observed_dict.items()
        ]
        observation = ModelObservation(
            observed_items=obs_items,
            image_quality=ImageQuality(usable=True),
            occlusion_suspected=False,
        )

        checks_dict, verdict, operator_action = evaluate_pack_box(
            order_lines_str=r["order_lines"],
            observation=observation,
            candidate_skus=candidate_skus,
            config=cfg,
        )

        model_info = {
            "name": "sample-replay",
            "version": "1.0",
            "provider": None,
            "prompt_version": None,
            "calls": 0,
            "cost_usd": 0.0,
        }

        return _build_response_record(
            agent_input=agent_input, record_id=record_id, captured_at=sample_row["captured_at"], operator_id=operator_id,
            order_id=order_id, channel=channel, order_lines=r["order_lines"], candidate_skus=candidate_skus,
            checks=checks_dict, verdict=verdict, operator_action=operator_action, upstream_refs=upstream_refs,
            upstream_verdicts=upstream_verdicts, model_info=model_info, source="sample_replay",
            observation=observation, evidence_refs=refs, captured_at_source="sample_replay",
            image_refs=refs, image_sha256={},
        )

    # Path C: No inputs and not in sample data -> UNCERTAIN (insufficient_evidence)
    captured_at, captured_at_source = _resolve_captured_at(agent_input, [])
    checks = {
        "items_present": CheckResult("UNCERTAIN", "INSUFFICIENT_EVIDENCE", "No carton photo provided in inputs"),
        "quantities_correct": CheckResult("UNCERTAIN", "INSUFFICIENT_EVIDENCE", "No carton photo provided in inputs"),
        "no_extra_items": CheckResult("UNCERTAIN", "INSUFFICIENT_EVIDENCE", "No carton photo provided in inputs"),
    }
    return _build_response_record(
        agent_input=agent_input, record_id=record_id, captured_at=captured_at, operator_id=operator_id,
        order_id=order_id, channel=channel, order_lines=order_lines or "", candidate_skus=candidate_skus,
        checks=checks, verdict="UNCERTAIN", operator_action="STOP", upstream_refs=upstream_refs,
        upstream_verdicts=upstream_verdicts, model_info={"name": "none", "version": "0", "calls": 0},
        source="no_inputs_provided", observation=None, evidence_refs=[],
        captured_at_source=captured_at_source, image_refs=[], image_sha256={},
    )


def _build_response_record(
    *,
    agent_input: dict,
    record_id: str,
    captured_at: str,
    operator_id: str,
    order_id: str,
    channel: str,
    order_lines: str,
    candidate_skus: List[str],
    checks: Dict[str, CheckResult],
    verdict: str,
    operator_action: str,
    upstream_refs: List[str],
    upstream_verdicts: Dict[str, str],
    model_info: Dict[str, Any],
    source: str,
    observation: Optional[ModelObservation],
    evidence_refs: List[str],
    captured_at_source: str = "file_mtime",
    image_refs: Optional[List[str]] = None,
    image_sha256: Optional[Dict[str, str]] = None,
    offending_ref: Optional[str] = None,
    error_detail: Optional[str] = None,
    latency_ms: Optional[int] = None,
) -> dict:
    """Constructs, seals, and wraps a contract-compliant Agent Output."""
    contract_verdict = map_verdict(verdict)
    contract_outcome = map_outcome(verdict)

    contract_checks = [
        to_contract_check(key, res, evidence_refs=evidence_refs)
        for key, res in checks.items()
    ]

    reason_codes = {k: v.reason_code for k, v in checks.items()}
    causes = {k: v.cause for k, v in checks.items() if v.cause}

    bboxes = []
    observations_list = []
    if observation:
        for it in observation.observed_items:
            observations_list.append(it.to_dict())
            if it.bbox and len(it.bbox) == 4 and any(val > 0 for val in it.bbox):
                bboxes.append({"sku": it.sku, "bbox": it.bbox, "count": it.count})

    payload = {
        "channel": channel,
        "order_lines": order_lines,
        "source": source,
        "operator_action": operator_action,
        "captured_at_source": captured_at_source,
        "image_refs": image_refs or [],
        "image_sha256": image_sha256 or {},
        "verified_sha256": image_sha256 or {},
        "offending_ref": offending_ref,
        "error_detail": error_detail,
        "reason_codes": reason_codes,
        "causes": causes,
        "bounding_boxes": bboxes,
        "observations": observations_list,
        "upstream_verdicts": upstream_verdicts,
        "candidate_skus": candidate_skus,
    }

    record = build_record(
        agent_input,
        agent_id=AGENT_ID,
        record_id=record_id,
        captured_at=captured_at,
        operator_id=operator_id,
        unit_scope="order",
        refs={"order_id": order_id},
        checks=contract_checks,
        outcome=contract_outcome,
        model=model_info,
        reason=f"Pack verification verdict: {contract_outcome} ({contract_verdict})",
        inputs=agent_input.get("inputs", []),
        upstream_refs=upstream_refs,
        payload=payload,
        latency_ms=latency_ms,
    )

    # Keep produced_at equal to captured_at so that identical request replays produce
    # the exact same content_hash (stable content_hash for idempotent replays).
    record["produced_at"] = captured_at
    record = seal(record)

    out = build_output(
        record,
        next_step="continue" if contract_verdict == "PASS" else ("review" if contract_verdict == "UNCERTAIN" else "route_to_recovery"),
        reason=f"Pack outcome: {contract_outcome}",
    )
    out["timestamp"] = record["produced_at"]
    return out
