# Returns Manager

## Purpose

The Returns Manager evaluates a returned unit and produces a
Round 3 contract-compliant recommendation with traceable evidence.

## Processing pipeline

The adapted Returns business logic follows:

Vision
→ Identity
→ Completeness
→ Condition
→ Disposition

## Round 3 agent boundary

The agent accepts the shared Round 3 Agent Input:

- schema_version
- request_id
- workflow_id
- stage
- subject
- inputs
- previous_evidence
- context

The agent returns the shared Round 3 Agent Output containing:

- schema_version
- workflow_id
- stage
- agent_id
- status
- verdict
- confidence
- timestamp
- model
- error
- evidence

## Input layout

Returns inputs are read from:

data/input/<subject_id>/returns/

Expected inputs include:

- return_case.json
- one or more returned-item images

The case document provides structured information such as:

- org_id
- subject_id
- order_id
- ordered SKU
- ordered ASIN
- parts list
- missing parts
- captured_at
- operator information
- supplied Amazon condition information when available

## Checks

The Returns Manager produces these Round 3 checks:

- identity_match
- completeness
- condition

Each check may be:

- PASS
- FAIL
- UNCERTAIN

UNCERTAIN is preserved as a first-class outcome when the evidence is insufficient.

## Disposition

The recommended disposition is derived from the Returns evidence and
business checks.

Possible dispositions include:

- restock
- refurbish
- liquidate
- dispose
- pending_review

`operator_disposition` is retained as operator/reference information.
It is not used as the AI recommendation.

## Previous evidence

The agent accepts accumulated `previous_evidence[]` from the orchestrator.

Applicable upstream evidence may include:

- Receiving evidence
- Prep evidence
- Pack evidence

Upstream record IDs are preserved in the Returns Evidence Record as
`upstream_refs`.

The Returns agent does not call other agents directly.

## Missing input behavior

Required Returns inputs must not be silently ignored.

When a required document or image is missing, the agent returns an
explicit pending/error response rather than producing a successful
decision.

## Tenant isolation

The agent validates `org_id` and `subject_id` so a Returns case from
another organisation or subject cannot be processed for the current
request.

## HTTP interface

When running in HTTP mode:

GET /health

POST /run

Example server:

python -m uvicorn agents.returns.app:app --host 127.0.0.1 --port 8104

## Round 2 adaptation

The business logic was adapted from the Round 2 Returns repository.

The Round 3 implementation adds:

- shared Round 3 contract
- tenant validation
- safe input resolution
- explicit missing-input handling
- UNCERTAIN preservation
- previous_evidence handling
- upstream references
- operator-disposition separation
- Round 3 Evidence Record
- HTTP health/run interface

See `PROVENANCE.md` for the source repository and commit.

## Tests

Returns tests cover:

- contract validation
- identity
- completeness
- condition
- UNCERTAIN identity
- missing required input
- wrong tenant
- previous evidence
- operator disposition
- idempotency
