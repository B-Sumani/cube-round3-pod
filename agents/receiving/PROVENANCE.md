# Provenance: Receiving Manager

| | |
|---|---|
| **Round 2 repository** | https://github.com/SahanaNaidu-pixel/cube-01-receiving-manager |
| **Source commit** | `a45de41dae8de65dd78567270b6f0e07948d0554` ("Phase 1: Diagnose all controls, wire VITE_API_KEY auth, fix button text escaping") |
| **Round 2 repo left intact** | yes: nothing was pushed to it; Round 3 work happens only in this Pod repo |

## What was copied, and what changed

| Round 3 file | Round 2 source | Change |
|---|---|---|
| `r2/decision_engine.py` | `backend/app/core/decision_engine.py` | none (verbatim) |
| `r2/vision.py` | `backend/app/services/vision.py` | imports made package-relative; `analyze(settings, …)` takes settings instead of reading the Round 2 config module; two `print(DEBUG …)` lines removed (no request details in logs); token usage captured for cost reporting |
| `r2/models/po.py`, `evidence.py`, `inspection.py` | `backend/app/models/*` | none (verbatim) |

## What was NOT brought over (and why)

- The Round 2 FastAPI app, SQLite repository, API-key auth, upload pipeline and React UI. In Round 3 the **orchestrator** owns workflow state, storage and tenancy; the agent is a pure `handle(agent_input) -> agent_output` function (also served over HTTP by `shared.utils.server.make_app`).
- The Round 2 HMAC "seal" of records. The Pod contract uses `content_hash` (a content hash, **not** tamper-evidence).
- Round 2 `.env` and uploaded photos (`uploads/`): not copied. No secrets, no unreviewed images in this repo.

Uncommitted Round 2 working-tree changes at the time of the copy existed in `vision.py`; the copied file is the working-tree version at that commit. Diff it against the commit with `git diff a45de41 -- backend/app/services/vision.py` in the Round 2 repo.
