# Agent HTTP API (language-agnostic)

Any agent, in any language, plugs in by serving two endpoints. Set `"mode": "http"` and `"url"` in `agents/<stage>/agent.json` (or env `<STAGE>_URL`, e.g. `PREP_URL`). Python agents get this for free: `make_app(stage, handle)` in `shared/utils/server.py`.

## `GET /health`

```json
{ "status": "ok", "stage": "prep", "version": "1.2.0", "contract_version": "1.0",
  "idempotency": { "supported": true, "key": ["subject.org_id", "request_id"], "scope": "process", "durable": false,
                   "ttl_s": 900, "wait_s": 25 } }
```

`status` is `ok` or `degraded` (up, but a dependency such as the model API is failing). Return fast; do not call the model here.

`idempotency` is **optional capability negotiation** (D-117). Omit it, or send `{"supported": false}`, unless you implement every rule in [Idempotency](#idempotency-optional-capability) below. The orchestrator reads only `idempotency.supported`; any other value, a missing field, or an unreachable `/health` counts as **not supported**. The other fields describe your guarantee honestly: `scope` is `"process"` for in-memory state (`"shared"` if every worker and replica uses one store), and `durable` is `true` only if completed results survive a restart.

## `POST /run`

**Request body:** an [Agent Input](../schemas/agent-input.schema.json). Example: [`examples/end-to-end/agent-input.prep.json`](../../examples/end-to-end/agent-input.prep.json).

**Success `200`:** an [Agent Output](../schemas/agent-output.schema.json) containing an [Evidence Record](../schemas/evidence.schema.json). Examples: [`examples/`](../../examples/).

| Status | When | Orchestrator reaction |
|---|---|---|
| `200` | You produced an output, **including** a `pending` one when you could not judge. | Validates it, records the evidence, decides the transition. |
| `404` | Unknown subject, **or it belongs to another org.** Never answer a wrong-tenant request. | Refused, **not retried**, recorded as `agent_rejected`. |
| `422` | The input does not match the schema, or `stage` is not yours. | Refused, not retried. |
| `409` | (Idempotent agents) the same `(subject.org_id, request_id)` arrived with a **different** body. | Refused, not retried, recorded as `agent_rejected`. |
| `503` + `Retry-After` | (Idempotent agents) the same request is still running and did not finish within your wait bound. | Retried like any `5xx` (the agent is idempotent, so the retry cannot repeat the work). |
| `5xx` / timeout | Your service is broken, or did not answer in time. | **Connection never established** (refused, connect timeout): always retried, because the request was not delivered. **Delivered but no clean answer** (read timeout, `5xx`, connection dropped after sending): this is *ambiguous*, since the work may have happened. It is retried **only if `/health` advertises `idempotency.supported: true`**; otherwise it is recorded straight away as `agent_timeout` / `agent_unavailable` (event `retry_skipped`), and a `resume` re-runs it with a new `request_id`. |

Rules:

1. **Idempotent.** The same `request_id` yields the same `record_id`. Whether a *retry* can also avoid repeating side effects (model calls) is the optional capability above.
2. **Fail open.** If your model call fails, return `200` with a `pending` output (`verdict: "UNCERTAIN"`, `status: "pending"`, `error` set), not a `5xx`. Use `5xx` only when you could not even build an output.
3. **Read-only previous evidence.** Never modify it. Use the **latest override** in `context.overrides` as a record's effective verdict.
4. **Tenancy.** `evidence.subject.org_id` must equal the request's, or the orchestrator discards the output as a security event.
5. **Consistent.** `output.verdict`, `status` and `agent_id` must equal the evidence's; `content_hash` must verify.
6. **Time budget.** Respect `timeout_s` (default 30 s). Batch your model calls: one per unit carrying all checks.
7. **No secrets in responses or logs.**

## Idempotency (optional capability)

Python agents built with `make_app` get this automatically (switch it off with `AGENT_IDEMPOTENCY=off`). An agent in any other language may advertise `idempotency.supported: true` **only** if it does all of the following:

1. **Key** = (`subject.org_id`, `request_id`). Never serve one org's cached answer to another org.
2. **Execute once.** A request whose key is still running must not run the handler again. Wait for the running one, but only up to a bound below the orchestrator's `timeout_s`, then answer `503` with `Retry-After`.
3. **Replay.** A request whose key has completed gets the **same** answer again (same status, same body: same `record_id` and `content_hash`), with no new model call. `make_app` adds the header `Idempotent-Replay: true`.
4. **Same key, different body → `409`**, and nothing is executed. Compare a hash of the canonical JSON body.
5. **Never strand an entry.** Whatever happens to the HTTP connection (client gave up, cancelled), the execution settles its entry, either with an answer or by removing the key. Cache every *final* answer, including `pending` outputs and `404`; do not create an entry for a `422`.
6. **Be honest about scope.** In-memory state is per process: it is lost on restart and not shared between workers or replicas. A retry that lands on a different process, or arrives after the entry has expired, **will execute again**. Either run one worker per agent, share the store (e.g. Redis or a database with an atomic "insert if absent"), or do not advertise the capability.

**Not provided by the Python implementation:** durability across restarts, de-duplication across workers or replicas, or protection beyond `AGENT_IDEMPOTENCY_TTL_S` (default 900 s). A `resume` deliberately uses a new `request_id` (`…:r2`) and therefore executes again.

## Quick check

```sh
curl -s localhost:8102/health
curl -s -X POST localhost:8102/run -H 'content-type: application/json' \
     -d @examples/end-to-end/agent-input.prep.json | python -m json.tool | head -30
```
