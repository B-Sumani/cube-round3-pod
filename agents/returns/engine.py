
"""Round 3 Returns Manager business logic.

This module adapts the useful Round 2 Returns Manager pipeline:

    Vision
        ↓
    Identity
        ↓
    Completeness
        ↓
    Condition
        ↓
    Disposition recommendation

Round 3 contract/evidence construction is handled by app.py.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .r2_logic.completeness import assess_completeness
from .r2_logic.condition import assess_condition
from .r2_logic.disposition import recommend_disposition
from .r2_logic.fixture_model import FixtureVisionModel
from .r2_logic.identity import assess_identity
from .r2_logic.models import CheckResult, ReturnCase
from .r2_logic.vision_pipeline import (
    aggregate_observations,
    analyze_case_images,
    apply_vision_observation,
)


class MissingRequiredInputError(ValueError):
    """Raised when required Returns evidence is missing."""


def validate_required_images(case: ReturnCase) -> None:
    """Ensure every required return image exists."""

    if not case.photo_refs:
        raise MissingRequiredInputError(
            "No return-item images were supplied."
        )

    missing = [
        image_ref
        for image_ref in case.photo_refs
        if not Path(image_ref).is_file()
    ]

    if missing:
        raise MissingRequiredInputError(
            "Required return-item image(s) are missing: "
            + ", ".join(missing)
        )


def _adapt_identity_result(result: CheckResult) -> CheckResult:
    """Adapt the Round 2 identity check name to the Round 3 contract."""

    result.check_key = "identity_match"
    return result


def analyze_return(
    case: ReturnCase,
    vision_model=None,
) -> dict:
    """Run the Returns business logic for one returned unit.

    Args:
        case: Return case containing structured data and image references.
        vision_model: Optional compatible vision model. If omitted,
            the deterministic fixture model is used for testing/demo.

    Returns:
        A dictionary containing the updated case, check results,
        and recommended disposition.
    """

    # Round 3 must not silently ignore missing required evidence.
    validate_required_images(case)

    # Work on a copy so the original input object is not mutated.
    working_case = deepcopy(case)

    # ---------------------------------------------------------
    # 1. Vision
    # ---------------------------------------------------------

    model = (
        vision_model
        if vision_model is not None
        else FixtureVisionModel()
    )

    observations = analyze_case_images(
        working_case,
        model=model,
    )

    if not observations:
        raise MissingRequiredInputError(
            "No usable visual observations were produced."
        )

    aggregated = aggregate_observations(observations)

    if aggregated is not None:
        apply_vision_observation(
            working_case,
            aggregated,
        )

    # The Round 2 vision layer uses "match"/"uncertain",
    # while the Round 2 identity checker expects
    # "yes"/"no"/"uncertain".
    if working_case.identity_match == "match":
        working_case.identity_match = "yes"
    elif working_case.identity_match == "mismatch":
        working_case.identity_match = "no"

    # ---------------------------------------------------------
    # 2. Identity
    # ---------------------------------------------------------

    identity_result = _adapt_identity_result(
        assess_identity(working_case)
    )

    # ---------------------------------------------------------
    # 3. Completeness
    # ---------------------------------------------------------

    completeness_result = assess_completeness(
        working_case
    )

    # ---------------------------------------------------------
    # 4. Condition
    # ---------------------------------------------------------

    condition_result = assess_condition(
        working_case
    )

    # ---------------------------------------------------------
    # 5. Disposition recommendation
    # ---------------------------------------------------------

    recommended_disposition = recommend_disposition(
        identity=identity_result,
        completeness=completeness_result,
        condition=condition_result,
    )

    return {
        "case": working_case,
        "checks": [
            identity_result,
            completeness_result,
            condition_result,
        ],
        "recommended_disposition": recommended_disposition,
    }