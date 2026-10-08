from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------
# Allowed high-level verdicts
# ---------------------------------------------------------

VERDICTS = {"PASS", "FAIL", "UNCERTAIN"}

# The sample data uses these operational dispositions.
DISPOSITIONS = {
    "restock",
    "refurbish",
    "liquidate",
    "dispose",
    "pending_review",
}

# Observed states from the challenge reference data.
OBSERVED_STATES = {
    "factory_sealed",
    "opened_unused",
    "signs_of_use",
    "damaged",
    "empty_box",
    "uncertain",
}


# ---------------------------------------------------------
# Input: returned unit
# ---------------------------------------------------------

@dataclass
class ReturnCase:
    record_id: str
    unit_id: str
    org_id: str

    photo_refs: list[str] = field(default_factory=list)

    operator_id: Optional[str] = None
    captured_at: Optional[str] = None

    order_id: Optional[str] = None
    ordered_sku: Optional[str] = None
    ordered_asin: Optional[str] = None

    identity_match: Optional[str] = None

    parts_list: list[str] = field(default_factory=list)
    parts_missing: list[str] = field(default_factory=list)

    observed_state: Optional[str] = None

    # Keep this as a string.
    # We must NOT invent our own Amazon condition taxonomy.
    amazon_condition: Optional[str] = None

    operator_disposition: Optional[str] = None


# ---------------------------------------------------------
# Result of one check
# ---------------------------------------------------------

@dataclass
class CheckResult:
    check_key: str
    verdict: str

    confidence: Optional[float] = None
    detail: str = ""

    model_version: Optional[str] = None
    latency_ms: Optional[float] = None

    evidence_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(
                f"Invalid verdict '{self.verdict}'. "
                f"Expected one of: {sorted(VERDICTS)}"
            )

        if self.confidence is not None:
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError(
                    "Confidence must be between 0.0 and 1.0."
                )


# ---------------------------------------------------------
# Override information
# ---------------------------------------------------------

@dataclass
class Override:
    original_verdict: str
    revised_verdict: str
    reason: str

    operator_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.original_verdict not in VERDICTS:
            raise ValueError(
                f"Invalid original verdict '{self.original_verdict}'. "
                f"Expected one of: {sorted(VERDICTS)}"
            )

        if self.revised_verdict not in VERDICTS:
            raise ValueError(
                f"Invalid revised verdict '{self.revised_verdict}'. "
                f"Expected one of: {sorted(VERDICTS)}"
            )

        if not self.reason.strip():
            raise ValueError("Override reason cannot be empty.")


# ---------------------------------------------------------
# Final evidence / decision record
# ---------------------------------------------------------

@dataclass
class EvidenceRecord:
    record_id: str
    schema_version: str

    organization_id: str
    client_id: Optional[str]

    agent: str

    subject: dict[str, Any]

    captured_at: Optional[str]
    operator_label: Optional[str]

    images: list[str] = field(default_factory=list)

    checks: list[CheckResult] = field(default_factory=list)

    outcome: Optional[str] = None

    overrides: list[Override] = field(default_factory=list)

    status: str = "completed"

    content_hash: Optional[str] = None

    def __post_init__(self) -> None:
        if self.outcome is not None and self.outcome not in VERDICTS:
            raise ValueError(
                f"Invalid outcome '{self.outcome}'. "
                f"Expected one of: {sorted(VERDICTS)}"
            )