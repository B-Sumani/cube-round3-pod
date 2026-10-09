from .models import CheckResult, ReturnCase


def assess_identity(case: ReturnCase) -> CheckResult:
    """
    Assess whether the returned item matches the originally ordered item.

    The reference data defines identity_match as:
        yes
        no
        uncertain

    These map directly to:
        PASS
        FAIL
        UNCERTAIN
    """

    value = (case.identity_match or "").strip().lower()

    if value == "yes":
        return CheckResult(
            check_key="identity",
            verdict="PASS",
            confidence=1.0,
            detail="Returned item identity matches the ordered item.",
        )

    if value == "no":
        return CheckResult(
            check_key="identity",
            verdict="FAIL",
            confidence=1.0,
            detail="Returned item identity does not match the ordered item.",
        )

    if value == "uncertain":
        return CheckResult(
            check_key="identity",
            verdict="UNCERTAIN",
            confidence=0.0,
            detail="Identity could not be determined with sufficient evidence.",
        )

    return CheckResult(
        check_key="identity",
        verdict="UNCERTAIN",
        confidence=0.0,
        detail="Identity value is missing or unsupported.",
    )