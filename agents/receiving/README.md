# agents/receiving · Receiving Manager (integrated Round 2 agent)

**Owner:** Receiving Manager (`@Harish2300032959`; see `agent.json` and `.github/CODEOWNERS`) · **Provenance:** [PROVENANCE.md](PROVENANCE.md)

First stage for every unit. It checks a received supplier PO line against the purchase order (identity, cartons, units per carton, total quantity, damage, quality flags) and returns one Evidence Record. Every verdict comes from the **Round 2 deterministic rules** (`r2/decision_engine.py`). A model only reads values; it never decides.

| | |
|---|---|
| **Reads (inputs)** | `request.inputs`: images under `data/input/<unit>/receiving/` (content-addressed by the orchestrator); the PO line and receipt for the unit, looked up **scoped by `org_id`** |
| **Reads (previous evidence)** | nothing (first in the chain) |
| **Produces** | `identity_match`, `carton_count`, `units_per_carton`, `quantity`, `carton_damage`, `unit_damage`, `quality_flags` (recorded mode); `identity_match`, `variant_match`, `carton_count`, `units_per_carton`, `quantity`, `carton_damage`, `components` (vision mode) |
| **`decision.outcome`** | `accept` (PASS) · `accept_with_exceptions` (FAIL) · `reject` (identity FAIL) · `pending_review` (UNCERTAIN or model error) |
| **`subject.unit_scope`** | `po_line` (Round 2 receiving rows are PO lines, finding F-08) |

## Two perception modes (always declared in `model` and `payload.perception`)

| Mode | When | Model calls | What it is |
|---|---|---|---|
| `recorded` (default) | no image captures, or `RECEIVING_VISION` not `on`, or no API key | 0 | The operator's recorded counts/observations, run through the Round 2 rules. **Not perception.** `model.name = receiving-r2-rules`. |
| `vision` | image captures exist **and** `RECEIVING_VISION=on` **and** `OPENAI_API_KEY` set | **1 per unit** (all images batched) | Round 2 `VisionService`: the model reads values *blind to the PO*; readings below 0.6 confidence count as unseen; photos that disagree → UNCERTAIN; the rules compare with the PO. |

## Rules worth knowing (Round 2 behaviour kept)

- A value nobody saw is **UNCERTAIN**, never the PO value.
- Totals: a direct count, or cartons × units/carton. If they disagree → UNCERTAIN (`conflicting_evidence`). If the PO itself is inconsistent (cartons × units/carton ≠ qty) → UNCERTAIN.
- `units_per_carton` is checked separately from the total (the stub did not do this).
- A check that does not apply (`NOT_REQUIRED`, e.g. no components on the PO) is **omitted**. A check with no observation source (components in recorded mode) is omitted and listed in `payload.checks_not_performed`.
- Shortfall is labelled `payload.shortfall_side = "supplier"` (finding F-10): it supports a supplier dispute, never a channel claim.

## Failure behaviour

- Model error, timeout, invalid JSON or a model-invented `image_id` → `pending_output` (status `pending`, verdict UNCERTAIN, no checks, error `model_error`). The orchestrator retries by policy; it never becomes a PASS.
- An input `ref` that escapes the input root → refused the same way (path traversal).
- A subject under another `org_id` → `LookupError` → HTTP 404 / `AgentRejected`. It is never answered.
- Idempotent: `record_id = RCV-<unit>-<sha256(request_id)[:8]>`.

## Run

```sh
pytest tests/integration/test_receiving_agent.py tests/integration/test_agent_contracts.py
.venv/Scripts/uvicorn agents.receiving.app:app --port 8101     # Windows   (.venv/bin/uvicorn on Linux/macOS)
```

Vision mode: put photos in `data/input/<UNIT>/receiving/`, set `RECEIVING_VISION=on` and `OPENAI_API_KEY` in `.env`, then run the case.

## Limitations

- Recorded mode is only as good as the operator's receipt. The sample data has no per-component observations, so `components` is not judged there.
- Vision mode is covered by tests with a mocked model only. It has not been evaluated against labelled real photos, so we make no accuracy claim for it.
- `cost_usd` is `null` in vision mode (token usage is in `payload.usage`); we do not hard-code a price.
