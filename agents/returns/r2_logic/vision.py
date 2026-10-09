from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class VisionObservation:
    """
    Structured observations produced from return-item images.

    These are observations, not final PASS/FAIL decisions.
    """

    image_ref: str

    identity_observation: Optional[str] = None
    observed_state: Optional[str] = None

    observed_parts: list[str] = field(default_factory=list)
    missing_parts_observed: list[str] = field(default_factory=list)

    notes: list[str] = field(default_factory=list)

    confidence: Optional[float] = None


def validate_image_reference(image_ref: str) -> bool:
    """
    Check that an image reference exists and points to a file.
    """

    if not image_ref:
        return False

    path = Path(image_ref)

    return path.exists() and path.is_file()


def create_observation(
    image_ref: str,
    *,
    identity_observation: Optional[str] = None,
    observed_state: Optional[str] = None,
    observed_parts: Optional[list[str]] = None,
    missing_parts_observed: Optional[list[str]] = None,
    notes: Optional[list[str]] = None,
    confidence: Optional[float] = None,
) -> VisionObservation:
    """
    Create a structured vision observation.

    This function deliberately does not make a final business
    decision. The downstream Returns Manager checks remain
    responsible for verdicts.
    """

    if not validate_image_reference(image_ref):
        raise FileNotFoundError(
            f"Image reference does not exist: {image_ref}"
        )

    if confidence is not None and not 0.0 <= confidence <= 1.0:
        raise ValueError(
            "Confidence must be between 0.0 and 1.0."
        )

    return VisionObservation(
        image_ref=image_ref,
        identity_observation=identity_observation,
        observed_state=observed_state,
        observed_parts=observed_parts or [],
        missing_parts_observed=missing_parts_observed or [],
        notes=notes or [],
        confidence=confidence,
    )