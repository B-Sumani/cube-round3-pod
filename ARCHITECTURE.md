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

## Our Pod's architecture

> Status (2026-10-09): **Receiving is our integrated Round 2 agent. Prep, Pack, Returns and Recovery are still organiser stubs** (`implementation: organiser-stub` in each `agent.json`), until each owner brings their Round 2 agent in. Pod type: `standard` (default; confirm with the organisers).

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
  (Round 2       (stub)  │      (stub) │       (stub)   │      (stub; reads every
   rules +               └──────────────┴────────────────┴────▶ prior record +
   vision)                                                       fee report)
        │
        ▼
 FileStore out/workflows/*.json, out/evidence/*.json   (MemoryStore in tests)
```

### 2. What each agent really is

| Stage | Implementation | Model calls | Notes |
|---|---|---|---|
| Receiving | **Round 2 agent** (`agents/receiving/`, [PROVENANCE](agents/receiving/PROVENANCE.md)): Round 2 `decision_engine.py` verbatim plus Round 2 `VisionService` | 0 (recorded mode) / 1 per unit (vision mode) | Rules decide every verdict. Mode is declared in `model` and `payload.perception`. |
| Prep | organiser stub (CSV replay) | 0 | owner to integrate |
| Pack | organiser stub | 0 | owner to integrate |
| Returns | organiser stub | 0 | owner to integrate |
| Recovery | organiser stub | 0 | owner to integrate; already keeps F-10 shortfalls SILENT |

### 3. Orchestrator

The starter engine is kept. It is tested and matches D-001…D-004. State is a JSON workflow document per `(org, unit)`, written atomically (`tmp` + `replace`), so a restart resumes from the file. Timeouts: `timeout_s` is enforced for HTTP and, since D-110, for in-process agents too (worker thread; a late answer is discarded). Concurrency: one caller at a time per workflow (thread + OS file lock; a waiter gets 409 after `ORCH_LOCK_TIMEOUT_S`, D-115), and evidence is created atomically (D-116). Retries: `flow.defaults.retries` for `agent_timeout`/`agent_unavailable`; never for `agent_rejected`/`invalid_output`/`tenant_mismatch`. Evidence is immutable: re-writing a `record_id` with different content raises. Overrides are appended workflow entries that reference the superseded record; downstream agents receive them in `context.overrides`. See D-101…D-109.

### 4. Routing and final outcome

Routing: `flow.json` (D-000). Receiving always runs, then Prep for FBA or Pack for MFN, then Returns only if returned, then Recovery. Final outcome: `rollup.py` precedence `CLAIM_RECOMMENDED > EXCEPTION > INCOMPLETE > NEEDS_REVIEW > CLEAN`. UNCERTAIN is never turned into PASS. A Receiving UNCERTAIN sets `needs_human`, so the workflow is `BLOCKED` / `NEEDS_REVIEW` until an override is recorded.

### 5. Tenancy

Enforced in three places: (a) every agent looks up its subject scoped by `org_id` and raises `LookupError` → 404 / `AgentRejected` otherwise; (b) the orchestrator rejects any output whose evidence names another org or subject (`tenant_mismatch`); (c) **storage**: every store read and write is org-scoped (`TenantViolation`), and the API requires `X-Org-Id` and returns 404 for another org's workflow (D-106). Tests: `tests/integration/test_store_tenancy.py`, `test_agent_contracts.py::test_other_tenant_gets_nothing`, `test_receiving_agent.py::test_wrong_tenant_is_refused`.

### 6. Failure model (what we break in the demo)

| Injected | What happens |
|---|---|
| Receiving model error / timeout (vision mode) | Receiving returns a `pending` record (no checks, `model_error`). The orchestrator retries, then the workflow is `FAILED`, outcome `INCOMPLETE`, `provisional: true`. |
| Agent unreachable (HTTP mode, nothing listening) | `agent_unavailable` degraded record, then `FAILED`. |
| Invalid output / wrong tenant in output | Rejected before storage, error recorded, `FAILED`. |
| UNCERTAIN identity (e.g. UNIT-0029) | `BLOCKED` / `NEEDS_REVIEW`. `apply_override` by a named actor is recorded and the outcome re-derived; the original record is unchanged. |

### 7. Deployment

Local only so far: `make run` / `.\pod.ps1 run` (CLI) and `make serve` / `.\pod.ps1 serve` (API on :8100). Any agent can run as its own service with `uvicorn agents.<stage>.app:app` and `mode: http`. No public URL yet.

### 8. Known limits

- Four of five stages are still stubs. End-to-end results reflect stub logic for those stages.
- Receiving vision mode is tested with a mocked model only; there is no accuracy claim for it.
- `content_hash` is a content hash, not tamper-evidence: nothing anchors it.
- `X-Org-Id` scopes data but does not authenticate anyone.
- HTTP retries: agents built with `make_app` de-duplicate `(org_id, request_id)` **in memory, per process** (D-117). That is not durable and not shared across workers or replicas, so run such agents with one worker. The orchestrator retries an ambiguous failure (timeout or 5xx after sending) only for agents that advertise idempotency in `/health`. In-process retries are de-duplicated separately (D-112).
- A hung in-process agent thread cannot be killed; it is orphaned (its result discarded, it shares no state, D-111) but keeps using CPU / a model call until it ends. Long-running agents should run in `http` mode or enforce their own timeouts.
