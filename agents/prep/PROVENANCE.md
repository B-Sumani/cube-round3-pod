# Provenance — Prep Manager Agent

## Origin
- **Round 2 Source Repository:** Prep Manager agent merged via PR #9 (`feature/prep-r3`)
- **Owner / Contributor:** `@jpatty-vin`
- **Stage:** `prep`
- **Agent ID:** `prep-manager@1.0.0`
- **Implementation:** `real`

## Integrated Components

| Source File | Pod Target Module | Description & Changes |
|---|---|---|
| `engine.py` | `agents/prep/engine.py` | Core rules engine evaluating Amazon FBA prep compliance rules: polybag sealing, suffocation warning, FNSKU placement, barcode coverage, expiry legibility, and handling marks. Vision API adapter with Gemini (`gemini-2.5-flash`) and deterministic fallback rules. |
| `app.py` | `agents/prep/app.py` | Standard Round 3 `handle(request: dict) -> dict` entrypoint compatible with both in-process (`InProcClient`) and HTTP (`HttpClient` / FastAPI) execution modes. |
| `test_prep_agent.py` | `agents/prep/tests/test_prep_agent.py` | Unit tests for output contract validation, passing checks, UNCERTAIN handling, and cross-tenant rejection. |

## Round 3 Architectural Guarantees
1. **Perception Modes:** When `GEMINI_API_KEY` is provided, executes single batched vision call per unit with `gemini-2.5-flash`; otherwise evaluates deterministic rules (`prep-r2-rules`) against sample dataset observations.
2. **Schema & Hash Conformance:** Emits valid `agent-output` schema with deterministic record IDs (`PRP-<safe_req_id>`), SHA-256 sealed envelope (`content_hash`), and structured checks.
3. **Multi-Tenancy Enforcement:** Enforces subject ownership and rejects cross-tenant requests and cross-tenant upstream evidence by raising `LookupError` (mapped to `AgentRejected` / HTTP 404).
4. **Traceability:** Links all consumed prior stage records into `upstream_refs` and passes captured photos into `inputs`.
