"""Tiny FastAPI factory so any Python agent can expose the contract in a few lines.

    from shared.utils.server import make_app
    app = make_app("receiving", handle)        # uvicorn agents.receiving.app:app

`handle(agent_input) -> agent_output`. Non-Python agents: implement the same two endpoints
(see shared/contracts/agent-api.md).

Idempotency (D-117): POST /run executes once per (subject.org_id, request_id). A duplicate that arrives while the
first is running waits for it (up to AGENT_IDEMPOTENCY_WAIT_S, then 503 + Retry-After); one that arrives after it
finished gets the cached answer (header `Idempotent-Replay: true`); the same key with a different body gets 409.
In-memory, per process: see shared/utils/idempotency.py for what that does NOT cover.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import idempotency as idem
from .records import pending_output
from .schema import errors

CONTRACT_VERSION = "1.0"
_FROM_ENV = object()


def _execute(handle: Callable[[dict], dict], body: dict) -> tuple[int, object]:
    """Run the handler and turn every outcome into a final, JSON-safe HTTP answer (fail open)."""
    try:
        out = handle(body)
        return 200, json.loads(json.dumps(out))  # proves it serialises now, not at every replay
    except LookupError as exc:  # unknown subject / wrong tenant
        return 404, {"detail": str(exc)}
    except Exception as exc:  # fail open: always return an output
        return 200, pending_output(body, code="agent_exception", message=str(exc))
    except BaseException as exc:  # sys.exit() etc. in a handler must not kill the worker or strand the entry
        return 200, pending_output(body, code="agent_exception", message=f"{type(exc).__name__}: {exc}")


def make_app(stage: str, handle: Callable[[dict], dict], version: str = "0.0.0", idempotency=_FROM_ENV,
             max_workers: int = 32) -> FastAPI:
    """`idempotency`: an IdempotencyCache, None to disable, or omitted to configure from the environment."""
    app = FastAPI(title=f"CUBE {stage} agent", version=version)
    cache = idem.from_env() if idempotency is _FROM_ENV else idempotency
    # Handlers are blocking (model calls). They run here, never on the event loop, so the server keeps accepting
    # duplicates (which then wait) and health checks while a unit is being judged.
    pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"{stage}-agent")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "stage": stage, "version": version, "contract_version": CONTRACT_VERSION,
                "idempotency": cache.capability() if cache is not None else {"supported": False}}  # an empty cache is falsy

    def _answer(response: tuple[int, object], replay: bool) -> JSONResponse:
        status, payload = response
        return JSONResponse(status_code=status, content=payload,
                            headers={"Idempotent-Replay": "true"} if replay else None)

    @app.post("/run")
    async def run(request: Request):
        body = await request.json()
        problems = errors("agent-input", body)
        if problems or body.get("stage") != stage:
            raise HTTPException(status_code=422, detail=problems or [f"stage must be '{stage}'"])
        loop = asyncio.get_running_loop()
        if cache is None:
            return _answer(await loop.run_in_executor(pool, _execute, handle, body), replay=False)

        key = (body["subject"]["org_id"], body["request_id"])
        body_hash = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        try:
            state, future = cache.claim(key, body_hash)
        except idem.KeyReused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        if state == "new":
            def work(fut: Future = future) -> None:
                # Runs on the pool thread and ALWAYS settles the entry, even if the HTTP caller has gone away.
                try:
                    cache.resolve(key, fut, _execute(handle, body))
                except BaseException as exc:  # could not even build an answer: forget the key, wake waiters
                    cache.drop(key, fut, exc)
            try:
                pool.submit(work)  # not awaited directly: cancelling this request never cancels the work
            except BaseException as exc:  # e.g. the pool is shutting down: never leave a "running" entry behind
                cache.drop(key, future, exc)
                raise

        try:
            response = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), timeout=cache.wait_s)
        except asyncio.TimeoutError:
            return JSONResponse(status_code=503, headers={"Retry-After": "1"},
                                content={"detail": f"request {key[1]} is still running; retry for its result"})
        except Exception as exc:  # the execution was dropped
            return JSONResponse(status_code=500, content={"detail": f"agent could not answer: {exc}"})
        return _answer(response, replay=state != "new")

    return app
