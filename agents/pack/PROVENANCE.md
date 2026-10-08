# Provenance — Pack Manager Agent

## Origin
- **Round 2 Repository:** `https://github.com/B-Sumani/cube26-pck-0042-b-sumani.git`
- **Local Source Path:** `C:\Users\user\Desktop\Pack Manager\cube26-pck-0042-b-sumani`
- **Source Directory:** `submissions/b-sumani/agent/`
- **Source Commit SHA:** `efb6f138f7196dcd913069369990724a976646ad`
- **Owner / Contributor:** `@B-Sumani`

## Ported Components

| Round 2 Source File | Round 3 Target Module | Description & Changes |
|---------------------|-----------------------|-----------------------|
| `rules/config.py` | `agents/pack/config.py` | Pure dataclass configuration containing confidence thresholds, occlusion gating, timeouts, and check rules. Pydantic removed. |
| `models/parser.py` | `agents/pack/parser.py` | JSON extraction, markdown-fenced repair, trailing-comma repair, bounding-box clamping `[0.0, 1.0]`, and domain dataclasses (`ObservedItem`, `UnrecognisedItem`, `ImageQuality`, `ModelObservation`). |
| `models/base.py` | `agents/pack/parser.py` | `demote_unexpected_skus`: demotes non-candidate detected SKUs to `unrecognised_items` without making additional LLM calls. |
| `rules/evaluator.py` | `agents/pack/evaluator.py` | Deterministic rules engine evaluating 3 checks (`items_present`, `quantities_correct`, `no_extra_items`). Generates verdicts `SEAL`, `STOP_AND_FIX`, and `UNCERTAIN`. |
| `models/gemini.py` | `agents/pack/model_adapter.py` | On-demand `GeminiVisionAdapter` via `httpx.Client`. Header-based authentication (`x-goog-api-key`), structured JSON prompt, candidate SKU gating (order quantities never disclosed to vision model). `MockVisionAdapter` for deterministic testing. |
| New mapping layer | `agents/pack/mapping.py` | Maps internal domain verdicts and failure reasons to Round 3 contract vocabularies (`PASS`, `FAIL`, `UNCERTAIN`, `seal`, `stop_and_fix`, `pending_review`, and `uncertain_reason` enums). |
| New catalogue layer | `agents/pack/catalogue.py` | Tenant-scoped seller catalogue loading (`org_demo_alpha`, `org_demo_bravo`). Raises `LookupError` on unauthorized or cross-tenant access. |
| New pipeline engine | `agents/pack/engine.py` | Core orchestration logic: input ref directory-traversal prevention, SHA-256 byte integrity verification, candidate SKU compilation, single vision model execution, evidence record construction, and canonical JSON sealing. |
| Entrypoint | `agents/pack/app.py` | Thin `handle(agent_input: dict) -> dict` interface compatible with both in-process (`InProcClient`) and HTTP (`HttpClient` / FastAPI) execution modes. |

## Omitted & Cleaned Components

The following Round 2 components were intentionally excluded to align with the Round 3 headless Pod architecture:
- **Authentication & Sessions:** Login routes, session cookies, CSRF protection, and user tables.
- **Pack UI & Templates:** Jinja2 templates, static CSS/JavaScript, packing station operator web interface.
- **Pack Database:** SQLite/PostgreSQL schema and direct relational record storage (delegated entirely to the Round 3 orchestrator store).
- **Standalone Routes:** Web UI endpoints in `main.py` (replaced with contract-compliant `handle` and FastAPI `/run`, `/health` endpoints).
- **Pydantic Dependency:** Replaced with standard library `@dataclass` to avoid extra runtime dependencies.

## Round 3 Architectural Guarantees
1. **Single Model Call:** At most one vision model call per unit; candidate SKUs are presented in the prompt without revealing expected order quantities.
2. **Fail-Open Design:** Missing API keys, network timeouts, or provider errors yield contract-valid `UNCERTAIN` outputs with `pending` / `error` status and structured error codes (`model_error`) via `shared.utils.records.pending_output`.
3. **Strict Tenancy:** Rejects input file refs that escape `INPUT_DIR` and refuses cross-tenant catalogue lookups by raising `LookupError` (mapped to `AgentRejected` / HTTP 404).
4. **Idempotence & Cryptographic Sealing:** Deterministic record ID generation (`PCK-<subject_id>`) with pinned `produced_at` timestamp ensures identical `content_hash` across duplicate requests.
5. **Upstream Linkage:** Only consumed Receiving evidence record IDs are placed into `upstream_refs`. Operator overrides in `context.overrides` are honored when recording upstream verdicts in `payload.upstream_verdicts`.
