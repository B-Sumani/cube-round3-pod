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
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import httpx

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


class GeminiVisionAdapter(VisionModelAdapter):
    """Adapter for Google Gemini Vision models."""

    IS_MOCK: bool = False

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        total_timeout_budget: float = 15.0,
        max_transport_retries: int = 2,
    ):
        self._api_key = api_key
        self.model_name = model_name or os.getenv("MODEL_NAME", "gemini-3.1-flash-lite-preview")
        self.total_timeout_budget = total_timeout_budget
        self.max_transport_retries = max_transport_retries

    def _get_api_key(self) -> str:
        key = self._api_key or os.getenv("GEMINI_API_KEY", "")
        if not key or not key.strip() or key.startswith("your_"):
            raise ModelProviderError("GEMINI_API_KEY is not configured")
        return key.strip()

    def _build_prompt(
        self, candidate_skus: List[str], catalogue: Optional[Dict[str, Dict[str, str]]]
    ) -> str:
        sku_list = format_prompt_candidate_list(candidate_skus, catalogue or {})
        return (
            "You are inspecting a photograph of an open shipping box before it is sealed.\n"
            "Below is the seller's catalogue of candidate products that may be packed in this box:\n"
            f"{sku_list}\n\n"
            "Instructions:\n"
            "1. Carefully identify which candidate SKUs from the catalogue above are visible in the open box.\n"
            "2. For each SKU observed, count how many units are visible, report count_confidence (0.0 to 1.0) "
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
        for img_bytes in image_list:
            image_b64 = base64.b64encode(img_bytes).decode("utf-8")
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
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
        last_error: Optional[Exception | str] = None

        while attempts <= self.max_transport_retries:
            elapsed = time.monotonic() - start_time
            remaining_time = budget - elapsed
            if remaining_time <= 0:
                raise ModelTimeoutError(
                    f"Model call exceeded timeout budget of {budget:.1f}s after {attempts} attempts"
                )

            attempts += 1
            attempt_start = time.monotonic()

            try:
                logger.info(
                    "Calling Gemini model %s (attempt %d/%d, budget remaining: %.2fs)",
                    self.model_name,
                    attempts,
                    self.max_transport_retries + 1,
                    remaining_time,
                )
                with httpx.Client(timeout=remaining_time) as client:
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
                    if attempts <= self.max_transport_retries:
                        sleep_time = min(1.0 * attempts, max(0.1, remaining_time))
                        time.sleep(sleep_time)
                        continue
                    raise ModelProviderError(f"Exhausted retries ({attempts}): {last_error}")
                else:
                    raise ModelProviderError(f"Gemini API client error (HTTP {resp.status_code})")

            except httpx.TimeoutException as te:
                last_error = te
                raise ModelTimeoutError(f"Model call timed out: {te}") from te
            except httpx.RequestError as re:
                last_error = re
                if attempts <= self.max_transport_retries:
                    time.sleep(min(0.5 * attempts, max(0.1, remaining_time)))
                    continue
                raise ModelProviderError(f"Network request error: {re}") from re

        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        raise ModelProviderError(f"Failed to obtain observation: {last_error}")


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
    ):
        self.mock_observation = mock_observation
        self.simulate_timeout = simulate_timeout
        self.simulate_error = simulate_error
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
            raise ModelTimeoutError("Simulated mock timeout")
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
