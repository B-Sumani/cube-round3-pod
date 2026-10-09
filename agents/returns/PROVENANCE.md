# Returns Manager — Provenance

## Source repository

https://github.com/Vaishali-39/cube26-rtn-0236-vaishali-39

## Source stage

Returns Manager

## Source commit

c3e415d1e16a9c430161ea33e9f2f3308d87050b

## Imported / adapted Round 2 components

The Round 3 Returns agent reuses the useful Returns business logic from:

- vision.py
- vision_pipeline.py
- fixture_model.py
- model_adapter.py
- models.py
- identity.py
- completeness.py
- condition.py
- disposition.py

The Round 2 application entry point and standalone UI/database behavior are not used as the Round 3 agent boundary.

## Round 2 business pipeline retained

Vision
→ Identity
→ Completeness
→ Condition
→ Disposition

## Round 3 adaptations

- Implemented the shared Round 3 `handle(agent_input)` interface.
- Added Round 3 Agent Input / Agent Output contract handling.
- Added tenant (`org_id`) and subject validation.
- Added safe input resolution under `data/input/`.
- Added explicit missing-image and missing-document handling.
- Preserved `UNCERTAIN` as a first-class verdict.
- Mapped the Round 2 identity result to the Round 3 `identity_match` check key.
- Added `previous_evidence[]` consumption and upstream evidence references.
- Kept operator disposition as reference information rather than using it as the AI decision.
- Added Round 3 Evidence Record generation.
- Uses the starter's real evidence hashing mechanism.
- Added pending/error output for missing required input and agent exceptions.
- Added HTTP `/health` and `/run` endpoints through the Round 3 server adapter.

## Important behavioral corrections

The Round 3 adapter must not:

- silently continue when a required image is missing;
- convert `UNCERTAIN` into PASS or FAIL;
- treat `operator_disposition` as the AI recommendation;
- access another tenant's data;
- replace or mutate upstream evidence records.

## Current Round 3 implementation

The Round 3 agent boundary is:

Round 3 Agent Input
→ Returns adapter
→ adapted Round 2 business logic
→ checks
→ Evidence Record
→ Round 3 Agent Output
