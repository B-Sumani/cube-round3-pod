from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .vision import VisionObservation, create_observation


@dataclass
class ModelResponse:
    """Structured response returned by the vision model adapter."""

    observation: VisionObservation
    model_version: Optional[str] = None
    latency_ms: Optional[float] = None


class VisionModelAdapter:
    """
    Provider-independent interface for vision analysis.

    The actual AI provider can be connected later without changing
    the Returns Manager business logic.
    """

    model_version = "not-configured"

    def analyze(self, image_ref: str) -> ModelResponse:
        """
        Analyze an image.

        This base implementation validates the image reference.
        It does not pretend that an AI model has analyzed the image.
        """

        path = Path(image_ref)

        if not path.exists() or not path.is_file():
            raise FileNotFoundError(
                f"Image reference does not exist: {image_ref}"
            )

        observation = create_observation(image_ref)

        return ModelResponse(
            observation=observation,
            model_version=self.model_version,
            latency_ms=0.0,
        )