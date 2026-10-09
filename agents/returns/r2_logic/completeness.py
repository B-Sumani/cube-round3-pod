from .models import CheckResult, ReturnCase


def assess_completeness(case: ReturnCase) -> CheckResult:
    """
    Assess whether the returned item contains all expected parts.

    The reference data provides:
        parts_list    -> expected parts
        parts_missing -> parts that are missing

    Decision:
        No missing parts -> PASS
        One or more missing parts -> FAIL
        Missing/ambiguous evidence -> UNCERTAIN
    """

    expected_parts = [
        part.strip()
        for part in case.parts_list
        if part and part.strip()
    ]

    missing_parts = [
        part.strip()
        for part in case.parts_missing
        if part and part.strip()
    ]

    # If we have explicit missing parts, the item is incomplete.
    if missing_parts:
        return CheckResult(
            check_key="completeness",
            verdict="FAIL",
            confidence=1.0,
            detail=(
                "Expected parts are missing: "
                + ", ".join(missing_parts)
            ),
        )

    # If an expected parts list exists and nothing is missing,
    # completeness can be determined.
    if expected_parts:
        return CheckResult(
            check_key="completeness",
            verdict="PASS",
            confidence=1.0,
            detail="All expected parts are present.",
        )

    # We don't have enough information to determine completeness.
    return CheckResult(
        check_key="completeness",
        verdict="UNCERTAIN",
        confidence=0.0,
        detail="No reliable parts information is available.",
    )