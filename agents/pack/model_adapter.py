"""Vision model adapter for Pack Manager.

Ported from Round 2 models/gemini.py and models/mock.py.
Follows Round 3 constraints:
1. No automatic MockVisionAdapter fallback: missing API key raises ModelProviderError.
2. The mock adapter is injectable in tests only (IS_MOCK = True).
3. Client is created on-demand, NOT at module import time.
4. API key is sent via header ('x-goog-api-key'), NOT in the URL query string.
5. Never logs image bytes or API keys.
6. Exactly ONE model call per unit with structured response schema and transport retries.
7. Never sends order quantities to the model.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import httpx
from PIL import Image

from agents.pack.catalogue import format_prompt_candidate_list
from agents.pack.parser import (
    ModelError,
    ModelObservation,
    ModelParsingError,
    ModelProviderError,
    ModelTimeoutError,
    parse_and_validate_observation,
)

logger = logging.getLogger("pack_manager.adapter")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

GEMINI_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "observed_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "sku": {"type": "STRING"},
                    "count": {"type": "INTEGER"},
                    "count_confidence": {"type": "NUMBER"},
                    "identity_confidence": {"type": "NUMBER"},
                    "partially_occluded": {"type": "BOOLEAN"},
                    "bbox": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                },
                "required": [
                    "sku",
                    "count",
                    "count_confidence",
                    "identity_confidence",
                    "partially_occluded",
                    "bbox",
                ],
            },
        },
        "unrecognised_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "description": {"type": "STRING"},
                    "bbox": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                },
                "required": ["description", "bbox"],
            },
        },
        "image_quality": {
            "type": "OBJECT",
            "properties": {
                "usable": {"type": "BOOLEAN"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["usable", "issues"],
        },
        "occlusion_suspected": {"type": "BOOLEAN"},
        "notes": {"type": "STRING"},
    },
    "required": ["observed_items", "unrecognised_items", "image_quality", "occlusion_suspected"],
}


class VisionModelAdapter(ABC):
    """Abstract interface for Pack Manager vision adapters."""

    IS_MOCK: bool = False

    @abstractmethod
    def analyze_box(
        self,
        images: List[bytes] | bytes | None = None,
        candidate_skus: Optional[List[str]] = None,
        catalogue: Optional[Dict[str, Dict[str, str]]] = None,
        timeout_seconds: Optional[float] = None,
        *,
        image_bytes: Optional[bytes] = None,
    ) -> Tuple[ModelObservation, int, Dict[str, Any]]:
        """Analyzes open shipping box photograph(s).

        Returns:
            (ModelObservation, latency_ms, model_info_dict)
        """
        pass


def _detect_image_mime(data: bytes) -> str:
    """Detects MIME type from image magic bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    elif data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    elif data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return "image/jpeg"


def _prepare_image_for_model(img_bytes: bytes, max_dim: int = 1280, quality: int = 80) -> Tuple[bytes, str]:
    """Downscales image to a maximum of max_dim on the longest side and re-encodes as JPEG at quality ~80.

    Returns (prepared_bytes, mime_type).
    If the image cannot be opened/parsed by PIL, returns (original_bytes, _detect_image_mime(original_bytes)).
    """
    if not img_bytes:
        return img_bytes, "image/jpeg"
    try:
        with Image.open(io.BytesIO(img_bytes)) as img:
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            elif img.mode == "L":
                img = img.convert("RGB")

            width, height = img.size
            if max(width, height) > max_dim:
                scale = max_dim / float(max(width, height))
                new_width = max(1, int(round(width * scale)))
                new_height = max(1, int(round(height * scale)))
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            out_io = io.BytesIO()
            img.save(out_io, format="JPEG", quality=quality, optimize=True)
            return out_io.getvalue(), "image/jpeg"
    except Exception as exc:
        logger.warning("Could not resize image for model (%s); sending original bytes", exc)
        return img_bytes, _detect_image_mime(img_bytes)


class GeminiVisionAdapter(VisionModelAdapter):
    """Adapter for Google Gemini Vision models."""

    IS_MOCK: bool = False

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        total_timeout_budget: Optional[float] = None,
        max_transport_retries: int = 1,
    ):
        self._api_key = api_key
        self.model_name = model_name or os.getenv("MODEL_NAME", "gemini-2.5-flash")
        if total_timeout_budget is not None:
            self.total_timeout_budget = total_timeout_budget
        else:
            self.total_timeout_budget = float(os.getenv("AI_TIMEOUT_S", os.getenv("PACK_TIMEOUT_BUDGET", "45.0")))
        self.max_transport_retries = max_transport_retries

    def _get_api_key(self) -> str:
        key = self._api_key or os.getenv("GEMINI_API_KEY", "")
        if not key or not key.strip() or key.startswith("your_"):
            raise ModelProviderError("Vision key not configured on this server")
        return key.strip()

    def _build_prompt(
        self, candidate_skus: List[str], catalogue: Optional[Dict[str, Dict[str, str]]]
    ) -> str:
        sku_list = format_prompt_candidate_list(candidate_skus, catalogue or {})
        return (
            "You are inspecting photograph(s) of an open shipping box before it is sealed.\n"
            "Multiple views are inspected as different angles of the same box. Each physical item must be counted only once across all images.\n"
            "Below is the seller's catalogue of candidate products that may be packed in this box:\n"
            f"{sku_list}\n\n"
            "Instructions:\n"
            "1. Carefully identify which candidate SKUs from the catalogue above are visible in the open box.\n"
            "2. For each SKU observed, count how many units are visible across all angles (counting each physical item once), report count_confidence (0.0 to 1.0) "
            "and identity_confidence (0.0 to 1.0), whether it is partially occluded, and its bounding box [ymin, xmin, ymax, xmax].\n"
            "3. If you observe any item in the box that does NOT match any candidate SKU, add it to unrecognised_items "
            "with a description and bounding box.\n"
            "4. Inspect the image quality: mark usable as true/false, and list any issues (blur, glare, box_not_in_frame, dark).\n"
            "5. State whether occlusion is suspected (e.g. items stacked, hidden under packing material, or bottom not visible)."
        )

    def analyze_box(
        self,
        images: List[bytes] | bytes | None = None,
        candidate_skus: Optional[List[str]] = None,
        catalogue: Optional[Dict[str, Dict[str, str]]] = None,
        timeout_seconds: Optional[float] = None,
        *,
        image_bytes: Optional[bytes] = None,
    ) -> Tuple[ModelObservation, int, Dict[str, Any]]:
        raw_imgs = images if images is not None else image_bytes
        if isinstance(raw_imgs, (bytes, bytearray)):
            image_list = [bytes(raw_imgs)]
        elif raw_imgs:
            image_list = [bytes(b) for b in raw_imgs]
        else:
            image_list = []

        api_key = self._get_api_key()
        budget = timeout_seconds or self.total_timeout_budget
        start_time = time.monotonic()

        prompt_text = self._build_prompt(candidate_skus or [], catalogue)
        parts: List[Dict[str, Any]] = [{"text": prompt_text}]
        # Server-side downscaling to max 1280px and JPEG quality ~80, all photos batched in ONE call
        for img_bytes in image_list:
            prepared_bytes, mime_type = _prepare_image_for_model(img_bytes, max_dim=1280, quality=80)
            image_b64 = base64.b64encode(prepared_bytes).decode("utf-8")
            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": image_b64,
                }
            })

        url = GEMINI_API_URL.format(model=self.model_name)
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "response_schema": GEMINI_RESPONSE_SCHEMA,
                "temperature": 0.0,
            },
        }

        attempts = 0
        max_attempts = self.max_transport_retries + 1  # 1 retry = 2 attempts total
        last_error: Optional[Exception | str] = None

        while attempts < max_attempts:
            elapsed = time.monotonic() - start_time
            remaining_time = budget - elapsed
            if remaining_time <= 1.0:
                raise ModelTimeoutError(
                    f"Model call exceeded timeout budget of {budget:.1f}s after {attempts} attempts"
                )

            attempts += 1
            attempt_start = time.monotonic()

            if attempts < max_attempts and remaining_time > 15.0:
                call_timeout = min(25.0, remaining_time - 5.0)
            else:
                call_timeout = max(1.0, remaining_time)

            try:
                logger.info(
                    "Calling Gemini model %s (attempt %d/%d, budget remaining: %.2fs, call timeout: %.2fs)",
                    self.model_name,
                    attempts,
                    max_attempts,
                    remaining_time,
                    call_timeout,
                )
                with httpx.Client(timeout=call_timeout) as client:
                    resp = client.post(url, headers=headers, json=payload)

                attempt_latency = int((time.monotonic() - attempt_start) * 1000)
                logger.info("Gemini HTTP response: %d (%dms)", resp.status_code, attempt_latency)

                if resp.status_code == 200:
                    resp_json = resp.json()
                    candidates = resp_json.get("candidates", [])
                    if not candidates:
                        raise ModelProviderError("Empty candidates returned (safety filter block)")

                    raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    total_latency_ms = int((time.monotonic() - start_time) * 1000)

                    observation = parse_and_validate_observation(raw_text, candidate_skus)
                    model_info = {
                        "name": self.model_name,
                        "version": "1.0",
                        "provider": "google",
                        "prompt_version": "v1.0",
                        "calls": attempts,
                        "cost_usd": None,
                    }
                    return observation, total_latency_ms, model_info

                elif resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {resp.status_code}"
                    logger.warning("Gemini transient HTTP %d on attempt %d/%d", resp.status_code, attempts, max_attempts)
                    if attempts < max_attempts:
                        time_left = budget - (time.monotonic() - start_time)
                        if time_left > 2.0:
                            time.sleep(min(1.0, max(0.1, time_left - 1.0)))
                            continue
                    raise ModelProviderError(f"Exhausted retries ({attempts}): {last_error}")
                else:
                    # Non-retryable: 400 (Bad Request), 401/403 (Auth), 404, etc.
                    error_detail = ""
                    try:
                        error_detail = resp.text[:200]
                    except Exception:
                        pass
                    raise ModelProviderError(f"Gemini API client error (HTTP {resp.status_code}): {error_detail}")

            except httpx.TimeoutException as te:
                last_error = te
                logger.warning("Gemini call timed out on attempt %d/%d: %s", attempts, max_attempts, te)
                if attempts < max_attempts:
                    time_left = budget - (time.monotonic() - start_time)
                    if time_left > 2.0:
                        time.sleep(min(0.5, max(0.1, time_left - 1.0)))
                        continue
                raise ModelTimeoutError(f"Model call timed out: {te}") from te

            except httpx.RequestError as re:
                last_error = re
                logger.warning("Gemini network error on attempt %d/%d: %s", attempts, max_attempts, re)
                if attempts < max_attempts:
                    time_left = budget - (time.monotonic() - start_time)
                    if time_left > 2.0:
                        time.sleep(min(0.5, max(0.1, time_left - 1.0)))
                        continue
                raise ModelProviderError(f"Network request error: {re}") from re

        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        raise ModelTimeoutError(f"Model call timed out after {attempts} attempts: {last_error}")


class MockVisionAdapter(VisionModelAdapter):
    """Test-only mock adapter.

    Injectable in tests to verify deterministic behavior without network calls.
    """

    IS_MOCK: bool = True

    def __init__(
        self,
        mock_observation: Optional[ModelObservation] = None,
        simulate_timeout: bool = False,
        simulate_error: bool = False,
        timeout_attempts: int = 0,
    ):
        self.mock_observation = mock_observation
        self.simulate_timeout = simulate_timeout
        self.simulate_error = simulate_error
        self.timeout_attempts = timeout_attempts
        self.call_count = 0
        self.last_candidate_skus: List[str] = []
        self.last_images: List[bytes] = []

    def analyze_box(
        self,
        images: List[bytes] | bytes | None = None,
        candidate_skus: Optional[List[str]] = None,
        catalogue: Optional[Dict[str, Dict[str, str]]] = None,
        timeout_seconds: Optional[float] = None,
        *,
        image_bytes: Optional[bytes] = None,
    ) -> Tuple[ModelObservation, int, Dict[str, Any]]:
        self.call_count += 1
        self.last_candidate_skus = list(candidate_skus or [])
        raw_imgs = images if images is not None else image_bytes
        if isinstance(raw_imgs, (bytes, bytearray)):
            self.last_images = [bytes(raw_imgs)]
        elif raw_imgs:
            self.last_images = [bytes(b) for b in raw_imgs]
        else:
            self.last_images = []

        if self.simulate_timeout:
            raise ModelTimeoutError("The read operation timed out")
        if self.timeout_attempts > 0 and self.call_count <= self.timeout_attempts:
            raise ModelTimeoutError(f"Simulated mock timeout on attempt {self.call_count}")
        if self.simulate_error:
            raise ModelProviderError("Simulated mock provider error")

        if self.mock_observation:
            obs = self.mock_observation
            obs.demote_unexpected_skus(candidate_skus)
        else:
            obs = ModelObservation()

        model_info = {
            "name": "mock-adapter",
            "version": "1.0",
            "provider": "test",
            "prompt_version": "v1.0",
            "calls": 1,
            "cost_usd": 0.0,
        }
        return obs, 5, model_info
