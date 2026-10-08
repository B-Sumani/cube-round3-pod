# Provenance & Adaptation Log: Recovery Manager Agent

## Overview
- **Owner:** Haytham (@hayth31)
- **Agent Stage:** `recovery`
- **Agent ID:** `recovery@3.0.0`
- **Source Round 2 Repository:** `https://github.com/hayth31/cube26-rcy-0225-hayth31`

---

## Retained Round 2 Business Logic
1. **Fee Line Position Classification:**
   - Evaluates individual fee lines (`inbound_defect_fee`, `refund_issued_item_not_returned`, `fulfilment_fee_weight_tier`, `lost_inbound`) against upstream evidence.
2. **Tenant Isolation Enforcement:**
   - Strict `org_id` and `subject_id` checks. Demands valid authorization and lookup failure on foreign tenants (`LookupError`).
3. **Conservative Claim Verdicts:**
   - Claims are only recommended (`CONTRADICTS` -> `FAIL` verdict) when upstream evidence explicitly refutes the fee charge.
   - Insufficient evidence yields `SILENT` (`UNCERTAIN` verdict), which prevents false claims.

---

## Round 3 Refinements & Fixes Applied
1. **Removed Invented Claim Fallback Amounts:**
   - Stripped arbitrary \$25 and \$15 default fallbacks from Round 2 rules. Fee lines with \$0.00 or missing amounts are marked `SILENT` per finding **F-09** (Decision D-005).
2. **Weight-Tier & Lost Inbound Findings:**
   - Hardcoded weight tier claims set to `SILENT` due to lack of upstream measured weight (finding **F-07**).
   - Receiving shortfalls separated from channel losses (finding **F-10**).
3. **Shared Contract Integration:**
   - Adapted standard Round 3 `handle(agent_input: dict) -> dict` interface.
   - Generated standard SHA-256 verified `Evidence Record` (`RCY-<subject_id>`) with `upstream_refs` populated from prior stage evidence.
