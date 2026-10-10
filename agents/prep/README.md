# agents/prep/ · Prep Manager

**Owner:** @B-Sumani (Prep Manager) · Standard Pod 6
**Implementation:** Real Round 2 Agent (`agents.prep.app`)
**Mode:** `inproc` (also runnable via HTTP on port 8102)

| | |
|---|---|
| **Reads (inputs)** | Photos of prepped units, work orders, packaging observations |
| **Reads (previous evidence)** | Receiving evidence |
| **Produces** | Per-requirement compliance verdicts (`fnsku_label_placement`, `original_barcode_covered`, `handling_marks`) |
| **`decision.outcome` values** | `compliant`, `non_compliant`, `pending_review` |
| **Recovery Interaction** | Compliant evidence refutes false Amazon `inbound_defect_fee` and `prep_fee` charges |

## Architecture & Components

```text
agents/prep/
├── app.py          ← expose handle(agent_input: dict) -> dict (FastAPI app & inproc runner)
├── engine.py       ← deterministic prep rule evaluator + vision model caller
├── agent.json      ← implementation: real, owner: @B-Sumani, mode: inproc
├── PROVENANCE.md   ← Round 2 origin commit and ported components
├── requirements.txt← Agent dependencies (e.g. google-genai)
└── tests/          ← Unit and contract tests for the Prep agent
```

## Running the Agent

### In-Process (Default in Pod 6 Orchestrator)
Orchestrator invokes `agents.prep.app.handle(agent_input)` directly in-process with timeout and multi-tenant isolation.

### Standalone HTTP Service
```sh
uvicorn agents.prep.app:app --port 8102
curl http://localhost:8102/health
```
