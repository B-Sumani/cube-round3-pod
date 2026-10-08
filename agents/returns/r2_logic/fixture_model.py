from dataclasses import dataclass
from pathlib import Path

from .vision import VisionObservation


@dataclass
class FixtureVisionModel:
    """
    Deterministic vision model used for local development and testing.

    This maps the five local fixture images to structured observations.
    It is a test/demo model, not real AI inference.
    """

    model_version: str = "fixture-vision-v1"

    def analyze(self, image_ref: str) -> VisionObservation:
        path = Path(image_ref)

        if not path.exists() or not path.is_file():
            raise FileNotFoundError(
                f"Image not found: {image_ref}"
            )

        name = path.stem.lower()

        if name == "sealed_complete":
            return VisionObservation(
                image_ref=image_ref,
                identity_observation="match",
                observed_state="factory_sealed",
                observed_parts=[
                    "product",
                    "packaging",
                    "expected accessories",
                ],
                missing_parts_observed=[],
                notes=[
                    "Item appears factory sealed.",
                    "Expected components appear present.",
                ],
                confidence=1.0,
            )

        if name == "opened_unused":
            return VisionObservation(
                image_ref=image_ref,
                identity_observation="match",
                observed_state="opened_unused",
                observed_parts=[
                    "product",
                    "packaging",
                    "expected accessories",
                ],
                missing_parts_observed=[],
                notes=[
                    "Packaging appears opened.",
                    "No visible signs of use.",
                ],
                confidence=1.0,
            )

        if name == "missing_parts":
            return VisionObservation(
                image_ref=image_ref,
                identity_observation="match",
                observed_state="opened_unused",
                observed_parts=[
                    "product",
                    "packaging",
                ],
                missing_parts_observed=[
                    "expected component",
                ],
                notes=[
                    "An expected component appears to be missing.",
                ],
                confidence=1.0,
            )

        if name == "damaged_item":
            return VisionObservation(
                image_ref=image_ref,
                identity_observation="match",
                observed_state="damaged",
                observed_parts=[
                    "product",
                    "packaging",
                    "expected accessories",
                ],
                missing_parts_observed=[],
                notes=[
                    "Visible damage is present.",
                ],
                confidence=1.0,
            )

        if name == "uncertain_identity":
            return VisionObservation(
                image_ref=image_ref,
                identity_observation="uncertain",
                observed_state="uncertain",
                observed_parts=[],
                missing_parts_observed=[],
                notes=[
                    "Available visual evidence is insufficient "
                    "to establish item identity."
                ],
                confidence=0.0,
            )

        return VisionObservation(
            image_ref=image_ref,
            identity_observation="uncertain",
            observed_state="uncertain",
            observed_parts=[],
            missing_parts_observed=[],
            notes=[
                "Unknown fixture image; manual review is required."
            ],
            confidence=0.0,
        )