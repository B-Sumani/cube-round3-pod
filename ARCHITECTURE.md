# Architecture

This document describes the **starter**. At the bottom is a section for **your Pod's architecture**, which you must fill in and which is part of the submission. A submission whose `ARCHITECTURE.md` still only describes the starter has not documented its system.

## 1. The system

```text
                POD
                 │
       ┌─────────▼─────────┐      owns workflow state; derives status and final outcome from the evidence chain
       │    Orchestrator   │      routes · validates · records evidence · retries · handles failures and UNCERTAIN
       └─────────┬─────────┘
                 │  Agent Input ▼          ▲ Agent Output (evidence)
       ┌─────────▼─────────┐
       │     Receiving     │
       └─────────┬─────────┘
                 ↓
       ┌───────────────────┐
       │       Prep        │   (FBA units)
       └─────────┬─────────┘
                 ↓
       ┌───────────────────┐
       │       Pack        │   (merchant-fulfilled / 3PL units)
       └─────────┬─────────┘
                 ↓
       ┌───────────────────┐
       │      Returns      │   (if a return happened)
       └─────────┬─────────┘
                 ↓
       ┌───────────────────┐
       │     Recovery      │   reads ALL accumulated evidence
       └─────────┬─────────┘
                 ↓
          Final Outcome        derived by the orchestrator, not copied from any agent

  shared/schemas · shared/contracts · shared/utils      data/input · data/sample · data/expected      examples/
```

The arrows show the *expected commerce journey*. Physically, every hand-off goes through the orchestrator ([`INTEGRATION-GUIDE.md`](INTEGRATION-GUIDE.md) section 1).

## 2. Responsibilities

| Component | Responsible for | Not responsible for |
|---|---|---|
| **Agent** (`agents/<stage>/`) | One stage's judgment, returned as an Agent Output with an Evidence Record. Failing open. Refusing other tenants. | Calling other agents. Setting workflow state. Rewriting earlier evidence. |
| **Orchestrator** (`orchestration/`) | Starting workflows; identifying the current stage; invoking agents with context; validating and recording evidence; updating state; routing; retries; failures; UNCERTAIN; the final outcome. | Making stage judgments. Fabricating or deleting evidence. Turning UNCERTAIN into PASS/FAIL without an explicit rule. |
| **Contract** (`shared/schemas/`) | One strict set of data shapes. | Agent-specific logic (that goes in `payload`). |
| **Stubs** (`agents/*/app.py` as shipped) | Replaying Round 2 CSV rows as valid evidence, so the plumbing can be tested. | Pretending to be agents. |

## 3. Shared data

| Object | Owner | Lives in |
|---|---|---|
| Evidence Record | the agent that produced it (immutable) | the evidence store |
| Workflow State | **the orchestrator** | the workflow store |
| Overrides | the orchestrator records them; a person makes them | Workflow State (`overrides[]`), referencing evidence |
| Final Outcome | **the orchestrator**, derived | Workflow State (`final_outcome`) |
| Captures | the Pod | `data/input/<subject>/<stage>/`, referenced by `sha256` |

## 4. Evidence flow and workflow state

```text
Agent Result → Evidence Record → Orchestrator state transition → Next stage → New evidence → Updated workflow state → Final Outcome
```

- Each stage's evidence is stored and passed to **every later stage** as `previous_evidence`.
- State is `PENDING → IN_PROGRESS → COMPLETED`, or `FAILED` / `BLOCKED` / `RECOVERY_REQUIRED` ([`ORCHESTRATION-GUIDE.md`](ORCHESTRATION-GUIDE.md) section 5), always derived from the evidence and overrides.
- `transitions[]` is the audit trail.
- A reviewer can walk from the Final Outcome to `contributing_records`, to checks, to `evidence_refs`, to the `sha256` of the exact bytes examined.

## 5. Error handling

Every failure is **recorded and never becomes success**: a degraded evidence record stands in (no checks, UNCERTAIN, the error), the stage is `error`, the workflow `FAILED` with outcome `INCOMPLETE`. Transient failures retry; refusals and invalid output do not; UNCERTAIN is preserved; `resume` retries. Full table: [`ORCHESTRATION-GUIDE.md`](ORCHESTRATION-GUIDE.md) section 8. Tenancy: `org_id` on every request, record and workflow; a record about another org is rejected as a security event; **your storage must enforce it too**.

## 6. Final outcome

`CLEAN`, `CLAIM_RECOMMENDED`, `EXCEPTION`, `NEEDS_REVIEW` or `INCOMPLETE`, with the reason, the contributing evidence, `needs_human`, and `provisional` (true unless the workflow is `COMPLETED`). Default rules: [`ORCHESTRATION-GUIDE.md`](ORCHESTRATION-GUIDE.md) section 6.

## 7. What is fixed and what is yours

**Fixed (the contract, strict):**

- The five required agents and their stages (Specialist Pods: four agents plus integration work, see [`FAQ.md`](FAQ.md))
- Common evidence requirements: the Agent Input/Output and Evidence Record shapes; PASS / FAIL / UNCERTAIN; the status vocabularies
- Required traceability: workflow id, agent id, hashes, `upstream_refs`, overrides that reference what they supersede
- An orchestrator that owns workflow state and produces a **Final Outcome**
- Minimum testing, and the submission and evaluation requirements ([`SUBMISSION-GUIDE.md`](SUBMISSION-GUIDE.md), [`ROUND3-RUBRIC.md`](ROUND3-RUBRIC.md))

**Participant-designed (the implementation, flexible):**

- Internal architecture, programming language, frameworks, how each agent is built
- How the orchestrator is implemented (the starter is one option; LangGraph, a queue, a state machine, your own)
- The communication mechanism (in-process, HTTP, queue) as long as the contract holds
- Database, persistence, deployment platform
- UI, review queue, dashboards
- Additional services, additional features
- The final-outcome policy, routing and `on_uncertain` / `on_error` policies (documented in `docs/decisions.md`)

## 8. Extension points

| You want to… | Change |
|---|---|
| Add or reroute a stage | `orchestration/flow.json` (and write a decision) |
| Change the final decision or status rules | `orchestration/rollup.py` (and its tests, and a decision) |
| Plug in a real agent | `agents/<stage>/app.py` + `agent.json` |
| Run an agent as a service in any language | `agent.json` `mode: "http"` + [`agent-api.md`](shared/contracts/agent-api.md) |
| Run your own subjects | `data/input/<subject>/<stage>/` + a cases file |
| Add agent-specific data to evidence | `payload` (never the envelope) |
| Persist to a database | implement the four store methods in `orchestration/store.py` |

## 9. Deployment options (yours)

- **Single process:** `uvicorn orchestration.api:app` with all agents `inproc`. Simplest.
- **Orchestrator + agent services:** each agent its own process, `mode: "http"`, `<STAGE>_URL` set; `GET /health` for readiness.
- Whatever you pick, the demo runs from the submitted commit and any URL works without your accounts. The API ships with **no authentication**: add it before exposing it.

---

### Our Pod's architecture

> Status (2026-10-10): **Receiving, Pack, Returns and Recovery are integrated Round 2 agents. Prep is maintained strictly as an organiser stub** (`implementation: "organiser-stub"` in `agents/prep/agent.json`). Pod type: `standard`. Pod ID: `pod-06`.

### 1. Diagram

```text
 case {org_id, unit_id, route, returned}
        │
        ▼
 ┌──────────────────────── orchestrator (orchestration/) ─────────────────────────┐
 │ new_workflow → route each step (flow.json `when`) → build Agent Input          │
 │   (subject, inputs from data/input/<unit>/<stage>/ with sha256,                │
 │    ALL previous evidence, context.overrides)                                   │
 │ → client (inproc | http) → validate output (schema, stage, workflow, tenant,   │
 │   content_hash, consistency) → store evidence (org-scoped, immutable)          │
 │ → transition log → next stage … → rollup.py: status + Final Commerce Outcome   │
 └────────────────────────────────────────────────────────────────────────────────┘
        │            │ fba          │ mfn          │ returned      │
        ▼            ▼              ▼              ▼               ▼
   Receiving ──▶   Prep  ─┐      Pack  ─┐       Returns ─┐      Recovery
   (Round 2       (stub)  │      (Round 2│       (Round 2│      (Round 2; reads every
    rules +               └──────────────┴───────────────┴────▶ prior record +
    vision)                      rules)         rules)          fee report)
        │
        ▼
 FileStore out/workflows/*.json, out/evidence/*.json   (MemoryStore in tests)
```

### 2. What each agent really is

| Stage | Implementation | Owner | Model calls | Notes |
|---|---|---|---|---|
| **Receiving** | **Round 2 agent** (`agents/receiving/`, [PROVENANCE](agents/receiving/PROVENANCE.md)): Round 2 `decision_engine.py` verbatim plus Round 2 `VisionService` | @Harish2300032959 | 0 (recorded mode) / 1 per unit (vision mode) | Rules decide every verdict. Mode declared in `model` and `payload.perception`. Supplier shortfalls tagged as `shortfall_side = "supplier"` (F-10). |
| **Prep** | **Organiser stub** (CSV replay) | Organisers / Pending | 0 | Left as stub pending member integration. Clearly marked `[STUB REPLAY]` in checks and detail. Does not fabricate claims. |
| **Pack** | **Round 2 agent** (`agents/pack/`, [PROVENANCE](agents/pack/PROVENANCE.md)): Round 2 packaging assessment engine | @Vaishali-39 | 0 (rule-based) | Validates SKU barcode, packaging type, hazmat, unsealed liquids. Issues `stop_and_fix` on severe packaging defects. |
| **Returns** | **Round 2 agent** (`agents/returns/`, [PROVENANCE](agents/returns/PROVENANCE.md)): Round 2 return evaluation engine | @hayth31 | 0 (deterministic) | Evaluates return identity, completeness, condition grading, and disposition. Replays sample inputs cleanly when raw files are omitted. |
| **Recovery** | **Round 2 agent** (`agents/recovery/`, [PROVENANCE](agents/recovery/PROVENANCE.md)): Round 2 audit & dispute engine | @B-Sumani | 0 (audit rules) | Consumes ALL accumulated prior evidence. Disallow false claims on supplier shortfalls (F-10) or missing Prep evidence (F-07). |

### 3. Orchestration

The orchestrator (`orchestration/`) is the central control plane and single source of truth for the commerce pipeline:

- **State Ownership:** The orchestrator owns workflow state (`WorkflowState`). Individual agents never write state or decide the pipeline outcome; agents only emit an `AgentOutput` containing an immutable `EvidenceRecord`. Workflow state is written atomically (via tempfile and atomic file replacement or memory lock) and survives process restarts (`FileStore`).
- **The Flow:** Configured via `orchestration/flow.json`. Units are routed according to their attributes:
  - FBA units route through `receiving → prep → recovery`.
  - MFN / 3PL units route through `receiving → pack → recovery`.
  - Returns inspection (`returns`) runs if and only if `returned: true`.
  - Unrouted units (`route: "unknown"`) skip both prep and pack.
  - Every stage invocation carries the subject (`org_id`, `subject_id`), discovered stage inputs hashed with SHA-256, **all previous evidence records**, and active human overrides.
- **Status & Outcome Derivation:** Derived strictly via pure functions in `orchestration/rollup.py`:
  - **Status Precedence:** `FAILED` (if any stage errored or refused) > `BLOCKED` (if an unoverridden stage is UNCERTAIN with `needs_human` or policy `block`) > `RECOVERY_REQUIRED` (if an upstream failure preceded recovery) > `IN_PROGRESS` (if required stages remain pending) > `COMPLETED`.
  - **Final Outcome Precedence:** `CLAIM_RECOMMENDED` (recoverable channel fee disputed with contradicting evidence) > `EXCEPTION` (any stage failed/defective, e.g. carton damaged or pack `stop_and_fix`) > `INCOMPLETE` (workflow or required stage incomplete) > `NEEDS_REVIEW` (any stage UNCERTAIN) > `CLEAN` (all required stages PASS).
  - **Provisionality:** `final_outcome.provisional` is strictly `true` whenever `status != "COMPLETED"`.
  - **Evidence Backing:** `contributing_records` is guaranteed non-empty for every evaluated workflow.
- **Failure Handling:**
  - Strict validation of all agent outputs: schema conformance, correct stage name, workflow ID match, tenant match, content hash verification, and internal consistency.
  - Failures are **never** treated as success: an agent failure or rejection creates a degraded evidence record (`verdict: "UNCERTAIN"`, status `error`, no fabricated checks), and the workflow ends `FAILED` / `INCOMPLETE`.
  - Transient errors (`agent_timeout`, `agent_unavailable`) are retried according to `flow.defaults.retries`. Non-transient errors (`agent_rejected`, `tenant_mismatch`, `invalid_output`) are never retried.
  - `resume` re-runs errored or halted stages under a new request ID (`:r2`), preserving the original failed attempt's evidence record intact in the audit trail.
- **Tenancy:**
  - Multi-tenancy is enforced in depth: in agent handlers (raising `AgentRejected` / `LookupError`), in orchestrator output validation (detecting `tenant_mismatch`), and at storage level (`MemoryStore` and `FileStore` strictly enforce `org_id` on reads and writes, raising `TenantViolation`).
  - The API requires `X-Org-Id` and returns 404 for missing or mismatched tenant records to prevent tenant enumeration.

### 4. How to Swap in the Real Prep Agent

When the real Round 2 Prep agent is ready to be merged:
1. Copy the Prep code into `agents/prep/` (or deploy as an HTTP service).
2. Edit `agents/prep/agent.json`:
   - Change `"implementation": "organiser-stub"` to `"implementation": "real"`.
   - Update `"owner"` with the Prep owner's handle.
   - Set `"mode": "inproc"` (with `handle(request)` defined in `agents/prep/app.py`) or `"mode": "http"` (with endpoint configuration).
3. Ensure the Prep agent returns valid evidence with checks (`polybag_check`, `barcode_scannable`, `fragile_bubble_wrap`, etc.) and a SHA-256 sealed envelope.
4. Recovery will automatically consume the real Prep evidence and un-silence inbound defect fee claims when Prep evidence contradicts Amazon charges.
5. Verify with `pytest tests/integration/test_prep_handling.py` and `pytest tests/e2e/`.

### 5. Failure model (what we break in the demo)

| Injected | What happens |
|---|---|
| Receiving model error / timeout (vision mode) | Receiving returns a `pending` record (no checks, `model_error`). The orchestrator retries, then the workflow is `FAILED`, outcome `INCOMPLETE`, `provisional: true`. |
| Agent unreachable (HTTP mode, nothing listening) | `agent_unavailable` degraded record, then `FAILED`. |
| Invalid output / wrong tenant in output | Rejected before storage, error recorded, `FAILED`. |
| UNCERTAIN identity (e.g. UNIT-0029) | `BLOCKED` / `NEEDS_REVIEW`. `apply_override` by a named actor is recorded and the outcome re-derived; the original record is unchanged. |
| Pack defect (`stop_and_fix`) | `EXCEPTION` outcome with `needs_human: true`. Package held on line until human override. |

### 6. Deployment

- **In-process (single process):** `python -m orchestration.run` (CLI) or `uvicorn orchestration.api:app --port 8100` (API).
- **HTTP mode:** Run each agent with `uvicorn agents.<stage>.app:app --port <port>` and set `<STAGE>_URL`.
- **UI:** Single Page Application under `ui/` built with Vite (`npm run build` -> `ui/dist/`), communicating with orchestrator API at `/workflows`, `/workflows/{id}`, `/workflows/{id}/evidence`, etc.

### 7. Known limits

- **Prep is an organiser stub:** Prep stage remains a stub until integrated. It replays CSV rows, is labelled `organiser-stub`, and does not fabricate claims.
- **Receiving vision mode:** Tested deterministically in recorded mode; live vision mode requires Gemini API credentials.
- **In-process thread cancellation:** Python cannot kill running threads; timed-out threads are orphaned and their delayed results discarded without corrupting store state.
- **Storage locking scope:** File locks are process-safe on a single host (`msvcrt`/`fcntl`); multi-node deployments require distributed locking (e.g. Redis/PostgreSQL).
