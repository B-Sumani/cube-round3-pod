from .models import CheckResult, ReturnCase


# These are the condition labels from Amazon's published
# general condition guidance.
#
# We intentionally do NOT create a custom condition scale.
AMAZON_CONDITIONS = {
    "New",
    "Renewed",
    "Rental",
    "Used - Like New or Open Box",
    "Used - Very Good",
    "Used - Good",
    "Used - Acceptable",
    "Collectible",
}


def assess_condition(case: ReturnCase) -> CheckResult:
    """
    Assess the returned item's condition.

    Important:
    observed_state is evidence/observation, not itself an
    Amazon condition grade.

    If an authoritative condition value has already been
    supplied, validate and preserve it.

    If only an observation is available and it is not enough
    to establish an exact condition grade, return UNCERTAIN
    rather than inventing a condition.
    """

    supplied_condition = (
        (case.amazon_condition or "").strip()
    )

    # -----------------------------------------------------
    # Case 1: An authoritative condition grade is available
    # -----------------------------------------------------

    if supplied_condition:
        if supplied_condition in AMAZON_CONDITIONS:
            return CheckResult(
                check_key="condition",
                verdict="PASS",
                confidence=1.0,
                detail=(
                    f"Condition classified as "
                    f"'{supplied_condition}' using the "
                    f"published condition taxonomy."
                ),
            )

        # Never silently accept an invented condition label.
        return CheckResult(
            check_key="condition",
            verdict="UNCERTAIN",
            confidence=0.0,
            detail=(
                f"Unsupported condition value "
                f"'{supplied_condition}'. "
                "Manual review is required."
            ),
        )

    # -----------------------------------------------------
    # Case 2: No authoritative condition grade is available
    # -----------------------------------------------------

    observed_state = (
        (case.observed_state or "").strip().lower()
    )

    if observed_state == "uncertain":
        return CheckResult(
            check_key="condition",
            verdict="UNCERTAIN",
            confidence=0.0,
            detail=(
                "The available visual observation is "
                "explicitly uncertain."
            ),
        )

    if observed_state == "factory_sealed":
        return CheckResult(
            check_key="condition",
            verdict="UNCERTAIN",
            confidence=0.5,
            detail=(
                "The item was observed as factory sealed, "
                "but an exact published condition grade "
                "has not been established from the available "
                "evidence."
            ),
        )

    if observed_state == "opened_unused":
        return CheckResult(
            check_key="condition",
            verdict="UNCERTAIN",
            confidence=0.5,
            detail=(
                "The item was observed as opened but unused. "
                "Additional evidence is required before "
                "assigning an exact published condition grade."
            ),
        )

    if observed_state == "signs_of_use":
        return CheckResult(
            check_key="condition",
            verdict="UNCERTAIN",
            confidence=0.5,
            detail=(
                "Signs of use were observed, but the available "
                "evidence is insufficient to distinguish the "
                "appropriate published used-condition grade."
            ),
        )

    if observed_state == "damaged":
        return CheckResult(
            check_key="condition",
            verdict="UNCERTAIN",
            confidence=0.5,
            detail=(
                "Damage was observed, but an exact published "
                "condition grade cannot be established from "
                "the observation alone."
            ),
        )

    if observed_state == "empty_box":
        return CheckResult(
            check_key="condition",
            verdict="UNCERTAIN",
            confidence=0.0,
            detail=(
                "The returned package was observed as an "
                "empty box. The condition of the actual "
                "product cannot be established."
            ),
        )

    # -----------------------------------------------------
    # Case 3: No usable condition evidence
    # -----------------------------------------------------

    return CheckResult(
        check_key="condition",
        verdict="UNCERTAIN",
        confidence=0.0,
        detail=(
            "Insufficient evidence to assign a published "
            "condition grade."
        ),
    )