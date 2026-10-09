from .fixture_model import FixtureVisionModel
from .models import ReturnCase
from .vision import VisionObservation


def apply_vision_observation(
    case: ReturnCase,
    observation: VisionObservation,
) -> ReturnCase:
    """
    Apply one visual observation to a ReturnCase.

    Vision produces observations only. Existing business checks
    remain responsible for PASS / FAIL / UNCERTAIN decisions.
    """

    if observation.identity_observation is not None:
        case.identity_match = observation.identity_observation

    if observation.observed_state is not None:
        case.observed_state = observation.observed_state

    if observation.missing_parts_observed:
        case.parts_missing = list(
            observation.missing_parts_observed
        )

    return case


def _aggregate_identity(
    observations: list[VisionObservation],
) -> str | None:
    values = {
        observation.identity_observation
        for observation in observations
        if observation.identity_observation
    }

    if not values:
        return None

    if "uncertain" in values:
        return "uncertain"

    if len(values) > 1:
        return "uncertain"

    return values.pop()


def _aggregate_state(
    observations: list[VisionObservation],
) -> str | None:
    values = {
        observation.observed_state
        for observation in observations
        if observation.observed_state
    }

    if not values:
        return None

    if "uncertain" in values:
        return "uncertain"

    if len(values) > 1:
        return "uncertain"

    return values.pop()


def _aggregate_missing_parts(
    observations: list[VisionObservation],
) -> list[str]:
    """
    Combine missing-part observations across all images.
    """

    missing_parts: set[str] = set()

    for observation in observations:
        missing_parts.update(
            observation.missing_parts_observed
        )

    return sorted(missing_parts)


def aggregate_observations(
    observations: list[VisionObservation],
) -> VisionObservation | None:
    """
    Aggregate multiple image observations into one observation.

    Conflicting identity or condition/state observations become
    UNCERTAIN instead of allowing the last image to overwrite
    earlier evidence.
    """

    if not observations:
        return None

    identity = _aggregate_identity(observations)
    state = _aggregate_state(observations)
    missing_parts = _aggregate_missing_parts(observations)

    observed_parts = sorted(
        {
            part
            for observation in observations
            for part in observation.observed_parts
        }
    )

    notes = [
        note
        for observation in observations
        for note in observation.notes
    ]

    confidences = [
        observation.confidence
        for observation in observations
        if observation.confidence is not None
    ]

    confidence = (
        min(confidences)
        if confidences
        else None
    )

    return VisionObservation(
        image_ref=";".join(
            observation.image_ref
            for observation in observations
        ),
        identity_observation=identity,
        observed_state=state,
        observed_parts=observed_parts,
        missing_parts_observed=missing_parts,
        notes=notes,
        confidence=confidence,
    )


def analyze_case_images(
    case: ReturnCase,
    model: FixtureVisionModel | None = None,
) -> list[VisionObservation]:
    """
    Analyze all available images associated with a ReturnCase.

    Missing image files are skipped so existing non-vision workflows
    remain usable.
    """

    model = model or FixtureVisionModel()

    observations = []

    for image_ref in case.photo_refs:
        try:
            observation = model.analyze(image_ref)
        except FileNotFoundError:
            continue

        observations.append(observation)

    return observations