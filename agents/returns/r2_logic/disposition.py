from .models import CheckResult


ALLOWED_DISPOSITIONS = {
    "restock",
    "refurbish",
    "liquidate",
    "dispose",
    "pending_review",
}


def recommend_disposition(
    identity: CheckResult,
    completeness: CheckResult,
    condition: CheckResult,
) -> str:
    """
    Recommend the next operational disposition for a returned item.

    Possible outcomes:
        restock
        refurbish
        liquidate
        dispose
        pending_review

    The recommendation is deliberately conservative when evidence
    is uncertain.
    """

    # ---------------------------------------------------------
    # 1. Identity must be established before recovery decisions
    # ---------------------------------------------------------

    if identity.verdict == "UNCERTAIN":
        return "pending_review"

    if identity.verdict == "FAIL":
        return "pending_review"

    # ---------------------------------------------------------
    # 2. Completeness uncertainty requires review
    # ---------------------------------------------------------

    if completeness.verdict == "UNCERTAIN":
        return "pending_review"

    # ---------------------------------------------------------
    # 3. Condition uncertainty requires review
    # ---------------------------------------------------------

    if condition.verdict == "UNCERTAIN":
        return "pending_review"

    # ---------------------------------------------------------
    # 4. Known damaged condition
    #
    # A damaged product that has been assessed and can potentially
    # be recovered should go through refurbishment.
    # ---------------------------------------------------------

    condition_detail = condition.detail.lower()

    if "damaged" in condition_detail:
        return "refurbish"

    # ---------------------------------------------------------
    # 5. Incomplete but otherwise identified return
    #
    # Missing components mean it should not go directly back
    # onto the shelf.
    # ---------------------------------------------------------

    if completeness.verdict == "FAIL":
        return "refurbish"

    # ---------------------------------------------------------
    # 6. Complete + identified + acceptable condition
    #
    # This is the cleanest restock scenario.
    # ---------------------------------------------------------

    if (
        identity.verdict == "PASS"
        and completeness.verdict == "PASS"
        and condition.verdict == "PASS"
    ):
        return "restock"

    # ---------------------------------------------------------
    # 7. Safety fallback
    # ---------------------------------------------------------

    return "pending_review"


def disposition_check(
    identity: CheckResult,
    completeness: CheckResult,
    condition: CheckResult,
) -> CheckResult:
    """
    Return the recommended disposition as a structured CheckResult.

    This makes the disposition decision traceable alongside the
    other checks.
    """

    recommendation = recommend_disposition(
        identity=identity,
        completeness=completeness,
        condition=condition,
    )

    if recommendation == "pending_review":
        return CheckResult(
            check_key="disposition",
            verdict="UNCERTAIN",
            confidence=0.0,
            detail=(
                "Disposition requires review because one or more "
                "upstream checks are uncertain or failed."
            ),
        )

    return CheckResult(
        check_key="disposition",
        verdict="PASS",
        confidence=1.0,
        detail=f"Recommended disposition: {recommendation}.",
    )