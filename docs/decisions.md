# Decisions

Every non-obvious design choice gets one entry, so a reviewer can see **what you chose, why, and what you rejected.** Newest last. This is where *Decision quality* and *Orchestration* in the [rubric](../ROUND3-RUBRIC.md) are won or lost. It is not meant to become a long report: a few lines per decision.

Write an entry whenever you: change the flow or its policies; change how the orchestrator stores state or evidence; change the final-outcome or status rules; choose a communication mechanism; decide how retries and overrides work; pick a side on a **known finding** (below); add to the contract's `payload`; or choose a deployment shape.

## Template

```text
### D-NNN · Short title
- Date / Owner:
- Context: what forced a decision?
- Options considered: A, B, C
- Decision: what we chose
- Why: the evidence or reasoning
- Consequences: what gets easier / harder; what would make us revisit
```

## Questions your Pod's decisions should answer

- Why this orchestration approach, and who owns what in it?
- Why this communication mechanism (in-process, HTTP, queue)?
- How is workflow state stored, and how does it survive a restart?
- How are retries, timeouts and resume handled?
- How is evidence persisted, and how is its immutability enforced?
- How are overrides captured, referenced, and used downstream?
- What do we do about UNCERTAIN: continue or block, and who decides?
- How does the final outcome treat weak or uncertain evidence?

## Starter decisions (made by the organisers; change them with a new entry)

### D-000 · The default flow is routed, not strictly sequential
- Context: the Round 2 sample gives each unit a Prep record *or* a Pack record, never both, and Returns only for returned units.
- Decision: `flow.json` routes FBA units through Prep, merchant-fulfilled units through Pack, and runs Returns only when a return happened. A stage that does not apply is `skipped` with the reason recorded.
- Why: forcing every unit through all five stages would invent evidence. Units with neither route (F-12) skip both.

### D-001 · The orchestrator owns state; status and outcome are derived
- Decision: workflow status and final outcome are pure functions of the stored evidence and the overrides (`orchestration/rollup.py`). Agents return evidence and a recommendation; they never write state.
- Why: "the latest agent outcome" and "Recovery's reading of it" are not the source of truth; the traceable evidence chain is.

### D-002 · UNCERTAIN continues by default; blocking is a policy
- Decision: `on_uncertain: continue` by default; `block` halts only when the UNCERTAIN result asks for a person (`needs_human`). Either way the workflow is `BLOCKED` with outcome `NEEDS_REVIEW` until an override resolves it.
- Why: a warehouse line must not wait, and the evidence of later stages is not lost. Recovery's SILENT (UNCERTAIN, `needs_human: false`) must not halt anything.

### D-003 · Failures are recorded, never hidden; never success
- Decision: a failed stage gets a degraded evidence record (no checks, UNCERTAIN, the error) and the workflow ends `FAILED` / `INCOMPLETE` (`provisional`). `resume` retries it and keeps the failed attempt's evidence.

### D-004 · Overrides are workflow entries that reference evidence
- Decision: evidence is immutable. A person's override is appended to the workflow's `overrides` with actor, reason, timestamp, the record it supersedes, the previous effective verdict and the new one. The latest wins; downstream agents receive them in `context.overrides`.

### D-005 · Zero-amount reimbursements are not claimable (F-09)
- Decision: the Recovery stub treats a 0.00 line as SILENT. Why: claiming $0 is meaningless and the meaning of 0.00 is unresolved.

### D-006 · Field names (F-15)
- Decision: `check_key`, `detail`, `content_hash`, `latency_ms`, `client_id` follow the Round 2 Returns list; `org_id`, `operator_id`, `inputs`, `model.version` follow the CSVs. Mapping in [`EVIDENCE-CONTRACT.md`](../EVIDENCE-CONTRACT.md). Open for the organisers.

## Known findings carried over from Round 2

Round 2 participants raised these contradictions and gaps in the shared data and documents. They are **open**: the organisers will rule on them. Until then **do not silently pick a side**: add an entry above with your assumption, and design so that changing it is cheap. `F-07` to `F-12` match the issue numbers on the Round 2 Recovery repo.

| ID | Finding | Why it matters for integration | Source |
|---|---|---|---|
| **F-07** | 42 of 61 sample fee lines are `fulfilment_fee_weight_tier`, and no upstream sample records measured weight or dimensions. | Recovery can only mark these SILENT. Prep is the natural source: see `payload.measurements`. | [Recovery #7](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/7) |
| **F-08** | `unit_id` means a **PO line** in Receiving (RCV-0003: 48 ordered, 44 received) but a **single unit** in the fee report. UNIT-0003 is lost inbound, then charged a fulfilment fee, then returned: that cannot be one physical unit. | Joins on a bare id can be wrong. The contract adds `subject.unit_scope` and `subject.refs`. | [Recovery #8](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/8) |
| **F-09** | A `lost_inbound` adjustment is posted with `amount_usd` 0.00. "Not reimbursed" (a claim to raise) or "amount missing"? | The answer flips the verdict. See D-005. | [Recovery #9](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/9) |
| **F-10** | Receiving shortfalls are supplier-side and happen before goods reach the channel, so they cannot support a channel `lost_inbound` claim. | Keep supplier shortfall and channel loss separate in your decision logic. | [Recovery #10](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/10) |
| **F-11** | Returns records exist for FBA-routed units (UNIT-0003 has a Prep record **and** a seller-side Returns record). Do FBA returns come back to the seller or to the channel's warehouse? | Decides whether Returns evidence can contradict `refund_issued_item_not_returned`. | [Recovery #11](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/11) |
| **F-12** | 9 of the 100 sample units have neither a Prep nor a Pack record, although each unit is meant to take one route. | The starter marks these `route: "unknown"` and skips both stages. Recovery's SILENT rate depends on it. | [Recovery #12](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/12) |
| **F-13** | The Round 2 rules said the organisers would provide an official evidence contract. None was published, and one participant's v0 proposal was withdrawn pending it. | **Resolved for Round 3:** [`EVIDENCE-CONTRACT.md`](../EVIDENCE-CONTRACT.md) v1.0. | [Receiving #4](https://github.com/Cube-Build-A-Thon/cube-01-receiving-manager/issues/4), [Recovery #13](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/13) |
| **F-14** | The Round 2 repos do not all carry the same rules: Receiving, Prep and Recovery share one short `RULES.md`; Pack's differs in wording; Returns has a much longer one (field names, evaluation method, mandatory LinkedIn post) that also ends mid-sentence. | Round 3 carries over the **union**; the organisers should confirm which is authoritative and finish the truncated section (presumably how Round 2 counts towards the final result). | [Returns `RULES.md`](https://github.com/Cube-Build-A-Thon/cube-04-returns-manager/blob/main/RULES.md) |
| **F-15** | The only organiser-authored list of "official evidence contract" fields is in the Returns repo (`organization_id`, `operator_label`, `images`, …) and is "concepts such as", not a schema. The sample CSVs use `org_id`, `operator_id`. | v1.0 uses a mix; see D-006 and the note at the top of [`EVIDENCE-CONTRACT.md`](../EVIDENCE-CONTRACT.md). | [Returns README](https://github.com/Cube-Build-A-Thon/cube-04-returns-manager/blob/main/README.md) |

### Raising a new finding

A contradiction between documents or data is a **finding**, not a failure. Open an issue on your Pod's repo with the `finding` label: what contradicts what, an example row, and what you assumed (and add the assumption above). Good findings are credited under *Decision quality*.

## Your Pod's decisions

_Add entries below._

### D-101 · Receiving: Round 2 rules decide, the model only reads
- Date / Owner: 2026-10-09 / Receiving (@Harish2300032959)
- Context: the stub compared CSV columns directly. The Round 2 agent has a stricter deterministic engine (units/carton, PO consistency, disagreeing readings) and a PO-blind vision reader.
- Options considered: A) port the Round 2 FastAPI service and call it over HTTP; B) copy the Round 2 core (`decision_engine.py`, `vision.py`, models) and wrap it in `handle()`; C) rewrite.
- Decision: B. The Round 2 state, storage, auth and UI were left out because the orchestrator owns those now.
- Why: one process, no duplicate state store, the Round 2 rules unchanged (verbatim copy, see `agents/receiving/PROVENANCE.md`).
- Consequences: the agent still serves over HTTP via `make_app`. Revisit if Receiving must scale separately.

### D-102 · Receiving has two declared perception modes
- Date / Owner: 2026-10-09 / Receiving
- Context: the shared data has no real photos. Vision needs an API key and costs money.
- Decision: `recorded` (default) runs the operator-recorded receipt through the Round 2 rules: `model.name = receiving-r2-rules`, 0 calls. `vision` (`RECEIVING_VISION=on` + key + image captures) makes **one batched call per unit**. The mode is written into `model` and `payload.perception`.
- Why: honesty. A recorded receipt is not perception and the evidence must say so. Batching keeps cost to one call per unit.
- Consequences: vision accuracy is unmeasured until we have labelled photos (see `docs/evaluation.md`).

### D-103 · Receiving check keys, omissions and uncertain reasons
- Decision: Round 2 names map to Pod keys (`sku_check→identity_match`, `carton_check→carton_count`, `units_per_carton_check→units_per_carton`, `quantity_check→quantity`, `damage_check→carton_damage`, `variant_check→variant_match`, `component_check→components`). `NOT_REQUIRED` checks are omitted, never PASS. A check with no observation source is omitted and listed in `payload.checks_not_performed`. Round 2 reason codes go into `check.detail`; `uncertain_reason` uses the contract enum (`NOT_OBSERVED→insufficient_evidence`, `VIEWS_DISAGREE/READINGS_DISAGREE→conflicting_evidence`, `LOW_VISIBILITY→poor_image`, `PO_*→other`).
- Consequences: downstream agents can rely on the recommended keys. `units_per_carton` is new but additive.

### D-104 · Receiving outcome mapping; supplier shortfall is labelled (F-10)
- Decision: PASS→`accept`; FAIL→`accept_with_exceptions`, except identity FAIL→`reject`; UNCERTAIN→`pending_review`. `payload.shortfall_side = "supplier"` whenever units are short.
- Why: F-10. A receiving shortfall supports a supplier dispute, never a channel `lost_inbound` claim. Recovery must keep it SILENT.

### D-105 · Receiving record ids are derived from request_id
- Decision: `RCV-<unit>-<sha256(request_id)[:8]>`. Same request gives the same id; a re-run (`:r2`) gives a new id, so the evidence store's immutability check never collides with the failed attempt's record.

### D-106 · Tenant isolation is enforced in storage, not only in the orchestrator
- Date / Owner: 2026-10-09 / Pod (orchestration)
- Decision: `MemoryStore`/`FileStore` take an `org_id` on every read and write. A cross-org access raises `TenantViolation` (a `LookupError`) rather than returning `None`, so a violation is loud and testable. The API maps it to the same 404 as a missing workflow, so tenant workflow ids can't be enumerated. A record id owned by one org can never be rewritten by another, even by an unscoped write. FileStore refuses path-like ids. `org_id=None` is kept only for tests and offline scripts.
- Consequences: the flat `out/{workflows,evidence}/` layout means record ids must be globally unique; stage prefixes plus subject ids guarantee that. `X-Org-Id` is a scoping key, **not authentication**. Real auth is needed before any public deployment.

### D-107 · A connect timeout is "unavailable", not "timeout"
- Decision: `httpx.ConnectTimeout` (we never connected) maps to `agent_unavailable`. `agent_timeout` is reserved for an agent that accepted the connection and did not answer in time. Both stay retryable.
- Why: on Windows a refused localhost connection is retried by the OS and surfaces as a connect timeout, so a dead agent was misclassified (baseline test failure on the starter).

### D-108 · Capture refs are POSIX paths
- Decision: `inputs[].ref` always uses `/`, so the same capture has the same ref and evidence hash on every OS (second baseline failure on Windows).

### D-109 · Windows is a supported dev platform
- Decision: `Makefile` picks `.venv/Scripts` on Windows; `pod.ps1` mirrors every make target for machines without `make`. CI stays Linux.

### D-110 · In-process agents get a real timeout
- Date / Owner: 2026-10-09 / Pod (orchestration)
- Context: `InProcClient` ignored `timeout_s`. One hung in-process agent (e.g. a model call with no client timeout) would block the workflow forever, which breaks the handbook's timeout requirement.
- Options considered: A) leave timeouts to each agent; B) run `handle()` on a worker thread and stop waiting after `timeout_s`; C) a subprocess per call.
- Decision: B. After `timeout_s` the orchestrator raises `AgentTimeout`, which is recorded as `agent_timeout`, retried by policy and never treated as success. Refusals (`LookupError`) and crashes keep their codes.
- Why: no extra dependencies, same semantics as HTTP mode. C would cost a process spawn per stage.
- Consequences: Python cannot kill a thread, so a hung agent keeps running in the background (as a daemon thread) and its late answer is discarded, never stored. A long-running real agent should run in `http` mode or enforce its own model timeout (Receiving does: `AI_TIMEOUT_S`).

### D-111 · Agents never share a mutable object with workflow state or stored evidence
- Date / Owner: 2026-10-09 / Pod (orchestration), from a review of D-110
- Context: an in-process agent received `previous_evidence` dicts that *were* the MemoryStore's stored records and `context.overrides` that *was* `wf["overrides"]`. An agent mutating its input, or a timed-out thread still running, could rewrite stored evidence or forge an override after the orchestrator moved on (reproduced).
- Decision: `InProcClient` gives the agent a deep copy of the request and returns a copy of the answer; `MemoryStore` copies evidence on write and on read (FileStore already serialises).
- Consequences: one JSON round-trip per call, negligible at our sizes.

### D-112 · At most one in-flight execution per request_id
- Context: a retry after an in-process timeout started a second, concurrent execution of the same request: a duplicate model call / side effect (reproduced).
- Decision: a retry with the same `request_id` re-joins the running execution and waits another `timeout_s`; if it answers inside that window, the answer is used once. A resume uses a new `request_id` (`:r2`), so it may start a fresh execution.
- Trade-off: a retry cannot "unstick" a hung in-process agent; only a resume can, and the old thread may then still be running. HTTP agents are not covered (see risks in ARCHITECTURE.md).

### D-113 · A store refusal of an agent's record is recorded, never a crash
- Context: `put_evidence` was unguarded. An agent reusing another record's id (immutability conflict), a path-like id, or a foreign-tenant record raised out of `advance()` and left no error record (reproduced for the id collision).
- Decision: such refusals become an `invalid_output` (or `tenant_mismatch`) degraded record; the workflow ends `FAILED`, and the original record is untouched.

### D-114 · The API refuses org ids that make workflow ids ambiguous
- Context: workflow ids are `WF-<org>-<unit>`. `POST /workflows` with org `org_demo_alpha-UNIT` + unit `0001` created `WF-org_demo_alpha-UNIT-0001`, squatting the real tenant's workflow id; the real tenant then got a 500 (reproduced). Path-like ids also produced 500s.
- Decision: `org_id` must match `[A-Za-z0-9_]+` (no `-`), and `unit_id` `[A-Za-z0-9][A-Za-z0-9_.-]*` without `..`; otherwise 422. All sample and Pod orgs already comply.
- Consequences: a real org id containing `-` would need a different workflow-id encoding (e.g. hashing) before onboarding.

### D-115 · One caller at a time per workflow (threads and processes)
- Date / Owner: 2026-10-09 / Pod (orchestration)
- Context (reproduced): three concurrent `run_workflow` calls on one case ran Prep three times. On the file store they crashed with `PermissionError` on a shared `WF-….tmp`. An override that arrived during a resume was lost, because the resume saved its stale copy. Two concurrent resumes re-ran the failed stage twice. Two processes (CLI + API) on one `out/` did the same.
- Options considered: A) optimistic concurrency (a version number checked on save, then retry); B) a per-workflow lock held across load → advance → save; C) a queue with one worker.
- Decision: B. `store.workflow_lock(workflow_id)` is a re-entrant thread lock per workflow. FileStore adds an OS advisory lock on `out/locks/<workflow_id>.lock` (`msvcrt` on Windows, `fcntl` elsewhere), released by the OS if the process dies, so a crash never leaves a stale lock. `run_workflow`, `resume` and `apply_override` hold it. A waiter gives up after `ORCH_LOCK_TIMEOUT_S` (default 300 s, the worst-case advance with the default flow) with `WorkflowBusy`, which the API returns as **409**; nothing is changed. Workflow saves use a unique temp file plus `os.replace`, retried briefly on Windows when a reader holds the file open.
- Why not A: with A, a stage can still run twice (both callers call the agent before either saves), and duplicate model calls are exactly what we want to avoid. C is more machinery than the Pod needs.
- Consequences: different workflows never wait on each other. A second caller for the same workflow waits for the first, then sees the result (completed stages are not re-run). The lock is advisory: only code that goes through the store obeys it. One small lock file is kept per workflow. Deleting lock files would race with a waiter, and the per-process lock dict grows by one entry per workflow touched.

### D-116 · Evidence creation is atomic
- Context (reproduced): `put_evidence` checked "exists?" and then wrote. Two writers of one record id could both pass the check: the file store silently overwrote the first record, the memory store silently dropped the second with no error, and two orgs racing for one id got no `TenantViolation`.
- Decision: creation is one atomic step that reports whether it won. FileStore writes the full record to a unique temp file and then `os.link`s it to the final name (which fails if the name exists), so creation is atomic across threads and processes and a reader never sees a half-written record. Filesystems without hard links fall back to exclusive create (`open(..., "x")`). MemoryStore inserts under a lock. The loser re-reads the winner's record: identical content is a no-op, different content raises `EvidenceConflict`, and another org's record raises `TenantViolation`. The original record is never touched.
- Consequences: one extra temp-file write per record. The `"x"` fallback can expose a partially written file to a concurrent reader on filesystems without hard links (not the case on NTFS, ext4 or APFS).

### D-117 · HTTP retries are de-duplicated by (org_id, request_id), and ambiguous failures are retried only for agents that say so
- Date / Owner: 2026-10-09 / Pod (orchestration + shared agent server)
- Context (reproduced): the orchestrator re-sent a request after any read timeout or `5xx`, and the agent server executed every copy: four concurrent duplicates made four handler (model) calls, and a re-sent completed request ran again. `make_app` also ran the blocking handler on the event loop, which serialised all requests (3.2 s for four 0.5 s calls).
- Options considered: A) server-side de-duplication on the existing `request_id` contract plus a capability flag in `/health`; B) a "202 Accepted, then poll" protocol; C) never retry ambiguous failures.
- Decision: A, with C as the fallback for agents that don't opt in.
  - **Agent server** (`shared/utils/server.py` + `shared/utils/idempotency.py`): one execution per `(subject.org_id, request_id)`. A duplicate waits for the running execution up to `AGENT_IDEMPOTENCY_WAIT_S` (25 s, below the default `timeout_s`), then gets `503` + `Retry-After`. A completed key replays the cached answer (`Idempotent-Replay: true`). Same key with a different body → `409`. Handlers run on a bounded thread pool, and the pool thread always settles its entry, so a disconnected or cancelled caller can never strand it. Every final answer is cached, including `pending` and `404` (re-running a `pending` would produce a different record under the same `record_id`, which the evidence store refuses, D-116). Completed entries expire after `AGENT_IDEMPOTENCY_TTL_S` (900 s) and are capped at `AGENT_IDEMPOTENCY_MAX_ENTRIES` (1000). Running entries are never evicted.
  - **Orchestrator** (`clients.py`, `orchestrator.py`): failures are classified by whether the request may have been delivered. Connect errors, connect timeouts and pool timeouts were not delivered, so they are always retried. Read/write timeouts, `5xx` and broken connections after sending are *ambiguous*: retried only if `/health` says `idempotency.supported: true` (asked lazily, once per client; unreachable or missing → not supported); otherwise the event is `retry_skipped`, recorded with the same `agent_timeout` / `agent_unavailable` code, and `resume` re-runs it with a new `request_id`. `InProcClient` is idempotent by construction (D-112). A plain `AgentTimeout` raised by other code is unchanged (not marked ambiguous), so starter tests and fakes behave as before.
- Why not B: it changes the protocol for every agent. Why not only C: it would lose the useful retry for agents that can support it.
- **Honest limits:** in memory, per process. Not durable across restarts, not shared across uvicorn workers or replicas, and gone after the TTL. Run agents that rely on it with one worker, or switch it off (`AGENT_IDEMPOTENCY=off`, which also stops advertising it). `/health` reports `"scope": "process", "durable": false`.
- Compatibility: the request and response schemas are unchanged. `/health` gains an optional `idempotency` field; old agents without it simply stop getting retries after *ambiguous* failures (a behaviour change, safer than a duplicate model call). New status codes `409` and `503` come only from agents that opt in. Non-Python agents: see `shared/contracts/agent-api.md#idempotency-optional-capability`.
