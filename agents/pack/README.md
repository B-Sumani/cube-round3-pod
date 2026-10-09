# agents/pack/ — Pack Manager Agent

- **Owner:** @B-Sumani
- **Agent ID:** `pack-manager@1.0.0`
- **Implementation:** `gemini-vision-deterministic-evaluator`
- **Provenance:** Ported from Round 2 submission [`submissions/b-sumani/agent/`](PROVENANCE.md) (`efb6f138`).

---

## 1. Overview

The **Pack Manager Agent** validates open shipping cartons at packing stations before sealing, exclusively for merchant-fulfilled/3PL orders (`route == "mfn"`). It verifies that:
1. Every SKU in the customer order lines is present inside the carton (`items_present`).
2. Piece counts of each expected item exactly match required quantities (`quantities_correct`).
3. No foreign, unrecognised, or extraneous items are packed into the carton (`no_extra_items`).

Its outputs form an immutable, cryptographically sealed Evidence Record (`PCK-...`) that downstream stages (Returns, Recovery) cite to prove what was originally dispatched.

---

## 2. Architecture & Modules

```text
agents/pack/
├── app.py              # Exposes handle(agent_input) -> Agent Output and FastAPI make_app()
├── engine.py           # Core pipeline: tenancy, SHA-256 checks, model call, record sealing
├── model_adapter.py    # Vision adapters: GeminiVisionAdapter (httpx) & MockVisionAdapter
├── parser.py           # JSON extraction, local string repair, bbox sanitizer, demote_unexpected_skus
├── evaluator.py        # Deterministic 3-check rules engine (PASS/FAIL/UNCERTAIN, SEAL/STOP_AND_FIX)
├── catalogue.py        # Org-scoped product catalogues and candidate SKU compiler
├── mapping.py          # Contract mapping for verdicts, outcomes, and uncertain_reasons
├── config.py           # Pure dataclass configuration (confidence thresholds, timeouts)
├── agent.json          # Agent registration manifest
├── PROVENANCE.md       # Origin repository, commit SHA, and migration details
├── README.md           # This document
└── tests/              # Comprehensive unit tests for pack engine, parser, rules, catalogue
```

---

## 3. Operational Contracts

| Property | Value / Specification |
|---|---|
| **Applicability** | MFN orders (`case.route == "mfn"`) |
| **Reads (Inputs)** | Top-down open-box carton photo (`kind="image"`), order lines |
| **Reads (Previous Evidence)** | Consumes only Receiving evidence (`stage == "receiving"`) |
| **Check Keys** | `items_present`, `quantities_correct`, `no_extra_items` |
| **Verdicts** | `PASS`, `FAIL`, `UNCERTAIN` |
| **Outcomes** | `seal`, `stop_and_fix`, `pending_review` |
| **Uncertain Reasons** | `poor_image`, `occluded`, `insufficient_evidence`, `model_error`, `conflicting_evidence` |
| **ID Pattern** | `^PCK-[A-Za-z0-9._-]+$` |

---

## 4. Key Engineering Guarantees

1. **Information Hiding:** Expected order quantities are never revealed to the vision model. The model receives only candidate SKU titles and visual descriptions, forcing independent visual counting.
2. **Single Model Call:** Exactly one vision model call is performed per unit. Non-candidate SKU detections are demoted to unrecognised items deterministically via `demote_unexpected_skus()` without second LLM queries.
3. **Fail-Open Behavior:** If the vision model times out, returns HTTP 5xx, or if `GEMINI_API_KEY` is unset, the agent returns a valid `UNCERTAIN` Agent Output (`status="pending"` or `"error"`, `code="model_error"`), never raising an uncaught exception or halting the pipeline.
4. **Strict Tenancy:** Rejects input file references containing `..` or escaping `INPUT_DIR`. Catalogues are partitioned per organisation (`org_demo_alpha`, `org_demo_bravo`); cross-tenant access immediately raises `LookupError` (`AgentRejected`).
5. **Deterministic Records:** Same `request_id` produces identical `record_id` and verified `content_hash` by pinning `produced_at` to the subject capture timestamp.

---

## 5. Running the Agent

### In-Process Mode (Default)
In `agents/pack/agent.json`:
```json
{
  "stage": "pack",
  "agent_id": "pack-manager@1.0.0",
  "owner": "@B-Sumani",
  "mode": "inproc",
  "module": "agents.pack.app",
  "implementation": "gemini-vision-deterministic-evaluator"
}
```

### Standalone HTTP Service
Set `"mode": "http"` in `agent.json` and start the server:
```sh
uvicorn agents.pack.app:app --port 8103
```
Test health:
```sh
curl http://localhost:8103/health
```

---

## 6. Testing

### Run All Pack Unit Tests:
```sh
python -m pytest agents/pack/tests -v
```

### Run Pack Integration Tests:
```sh
python -m pytest tests/integration/test_pack_agent.py -v
```

### Run Full Pod Test Suite:
```sh
python -m pytest -q
```
