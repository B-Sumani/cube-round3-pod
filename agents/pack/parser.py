"""JSON parsing, local string repair, and observation domain models.

Ported from Round 2 models/base.py and models/parser.py.
Eliminates Pydantic in favor of Python standard library dataclasses.
Zero second LLM calls: deterministic local string repair and schema validation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ModelError(Exception):
    """Base exception for vision model adapters."""
    pass


class ModelTimeoutError(ModelError):
    """Raised when the model call exceeds its total timeout budget."""
    pass


class ModelProviderError(ModelError):
    """Raised when the model provider returns an unrecoverable HTTP/API error."""
    pass


class ModelParsingError(ModelError):
    """Raised when model response cannot be parsed into a valid observation."""
    pass


@dataclass
class ObservedItem:
    sku: str
    count: int = 0
    count_confidence: float = 0.0
    identity_confidence: float = 0.0
    partially_occluded: bool = False
    bbox: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])

    def __post_init__(self) -> None:
        self.count = max(0, int(self.count))
        self.count_confidence = max(0.0, min(1.0, float(self.count_confidence)))
        self.identity_confidence = max(0.0, min(1.0, float(self.identity_confidence)))
        self.partially_occluded = bool(self.partially_occluded)
        self.bbox = _sanitize_bbox(self.bbox)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sku": self.sku,
            "count": self.count,
            "count_confidence": self.count_confidence,
            "identity_confidence": self.identity_confidence,
            "partially_occluded": self.partially_occluded,
            "bbox": self.bbox,
        }


@dataclass
class UnrecognisedItem:
    description: str
    bbox: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])

    def __post_init__(self) -> None:
        self.description = str(self.description)
        self.bbox = _sanitize_bbox(self.bbox)

    def to_dict(self) -> Dict[str, Any]:
        return {"description": self.description, "bbox": self.bbox}


@dataclass
class ImageQuality:
    usable: bool = True
    issues: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.usable = bool(self.usable)
        self.issues = [str(x) for x in self.issues]

    def to_dict(self) -> Dict[str, Any]:
        return {"usable": self.usable, "issues": self.issues}


@dataclass
class ModelObservation:
    observed_items: List[ObservedItem] = field(default_factory=list)
    unrecognised_items: List[UnrecognisedItem] = field(default_factory=list)
    image_quality: ImageQuality = field(default_factory=ImageQuality)
    occlusion_suspected: bool = False
    notes: Optional[str] = ""

    def demote_unexpected_skus(self, candidate_skus: List[str]) -> None:
        """Demotes any observed item whose SKU is outside candidate_skus to unrecognised_items.

        Enforces the candidate boundary: any hallucinated or non-candidate SKU is treated as unrecognised.
        """
        valid_candidates = set(candidate_skus)
        remaining_observed: List[ObservedItem] = []
        for item in self.observed_items:
            if item.sku in valid_candidates:
                remaining_observed.append(item)
            else:
                self.unrecognised_items.append(
                    UnrecognisedItem(
                        description=f"Non-candidate item reported as '{item.sku}' (count: {item.count})",
                        bbox=item.bbox,
                    )
                )
        self.observed_items = remaining_observed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observed_items": [item.to_dict() for item in self.observed_items],
            "unrecognised_items": [item.to_dict() for item in self.unrecognised_items],
            "image_quality": self.image_quality.to_dict(),
            "occlusion_suspected": self.occlusion_suspected,
            "notes": self.notes or "",
        }


def _sanitize_bbox(raw_bbox: Any) -> List[float]:
    """Ensures bbox contains exactly 4 floats [ymin, xmin, ymax, xmax]."""
    if not isinstance(raw_bbox, list):
        return [0.0, 0.0, 0.0, 0.0]
    try:
        nums = [float(v) for v in raw_bbox]
    except (ValueError, TypeError):
        return [0.0, 0.0, 0.0, 0.0]
    if len(nums) == 4:
        return nums
    if len(nums) >= 4 and len(nums) % 4 == 0:
        return [min(nums[0::4]), min(nums[1::4]), max(nums[2::4]), max(nums[3::4])]
    if len(nums) > 4:
        return nums[:4]
    return [0.0, 0.0, 1000.0, 1000.0]


def local_repair_json_string(raw: str) -> str:
    """Performs deterministic local string repairs without calling an LLM."""
    cleaned = raw.strip()

    # 1. Strip markdown code fences if present (```json ... ``` or ``` ...)
    fence_pattern = r"^```(?:json)?\s*([\s\S]*?)\s*```$"
    match = re.search(fence_pattern, cleaned, re.MULTILINE)
    if match:
        cleaned = match.group(1).strip()
    else:
        # Fallback: slice from first '{' to last '}'
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1].strip()

    # 2. Remove trailing commas before closing braces/brackets
    cleaned = re.sub(r",\s*([\}\]])", r"\1", cleaned)
    return cleaned


def parse_and_validate_observation(
    raw_text: str, candidate_skus: List[str]
) -> ModelObservation:
    """Parses model output string into a validated ModelObservation dataclass.

    Tries direct JSON parse; on decode error, applies deterministic local string repair.
    Demotes non-candidate SKUs to unrecognised_items.
    """
    if not raw_text or not raw_text.strip():
        raise ModelParsingError("Model returned empty or whitespace-only response")

    data: Dict[str, Any] = {}
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        repaired = local_repair_json_string(raw_text)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError as err:
            raise ModelParsingError(f"Failed to parse JSON even after local repair: {err}") from err

    if not isinstance(data, dict):
        raise ModelParsingError(f"Expected JSON object, got {type(data).__name__}")

    # Build ObservedItems
    raw_observed = data.get("observed_items", [])
    observed_items: List[ObservedItem] = []
    if isinstance(raw_observed, list):
        for it in raw_observed:
            if isinstance(it, dict) and "sku" in it:
                try:
                    observed_items.append(
                        ObservedItem(
                            sku=str(it.get("sku", "")),
                            count=it.get("count", 0),
                            count_confidence=it.get("count_confidence", 0.0),
                            identity_confidence=it.get("identity_confidence", 0.0),
                            partially_occluded=it.get("partially_occluded", False),
                            bbox=it.get("bbox", [0.0, 0.0, 0.0, 0.0]),
                        )
                    )
                except Exception as ex:
                    raise ModelParsingError(f"Invalid observed_item structure: {ex}") from ex

    # Build UnrecognisedItems
    raw_unrec = data.get("unrecognised_items", [])
    unrecognised_items: List[UnrecognisedItem] = []
    if isinstance(raw_unrec, list):
        for it in raw_unrec:
            if isinstance(it, dict):
                unrecognised_items.append(
                    UnrecognisedItem(
                        description=str(it.get("description", "unrecognised item")),
                        bbox=it.get("bbox", [0.0, 0.0, 0.0, 0.0]),
                    )
                )

    # Build ImageQuality
    raw_iq = data.get("image_quality", {})
    if isinstance(raw_iq, dict):
        image_quality = ImageQuality(
            usable=raw_iq.get("usable", True),
            issues=raw_iq.get("issues", []) if isinstance(raw_iq.get("issues"), list) else [],
        )
    else:
        image_quality = ImageQuality(usable=True, issues=[])

    observation = ModelObservation(
        observed_items=observed_items,
        unrecognised_items=unrecognised_items,
        image_quality=image_quality,
        occlusion_suspected=bool(data.get("occlusion_suspected", False)),
        notes=str(data.get("notes", "") or ""),
    )

    # Enforce candidate set boundary
    observation.demote_unexpected_skus(candidate_skus)
    return observation
