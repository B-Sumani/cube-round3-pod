"""HTTP retry idempotency (docs/decisions.md D-117): the agent server de-duplicates (org_id, request_id), and the
orchestrator retries an AMBIGUOUS failure (timeout / 5xx / broken connection after sending) only when the agent
advertises idempotency. A failure to connect (request never delivered) is always safe to retry.

Real uvicorn servers around counting handlers: the handler call count is the side-effect count (a model call).
"""
import copy
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from orchestration.clients import HttpClient
from orchestration.orchestrator import load_flow, run_workflow
from orchestration.store import MemoryStore
from shared.utils.idempotency import IdempotencyCache
from shared.utils.server import make_app
from tests.conftest import make_input
from tests.helpers import Fake

pytestmark = pytest.mark.http
CASE = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def serve():
    servers = []

    def start(app) -> str:
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        threading.Thread(target=server.run, daemon=True).start()
        url = f"http://127.0.0.1:{port}"
        for _ in range(200):
            try:
                httpx.get(f"{url}/health", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.02)
        servers.append(server)
        return url

    yield start
    for s in servers:
        s.should_exit = True


class Handler:
    """Counts executions (= side effects); optionally slow, failing or refusing."""

    def __init__(self, seconds=0.0, raise_=None, returns=None, gate=None):
        self.seconds, self.raise_, self.returns, self.calls = seconds, raise_, returns, 0
        self.gate = gate  # a threading.Event: the handler is "running" until the test sets it (no timing guesses)
        self.lock = threading.Lock()

    def __call__(self, request):
        with self.lock:
            self.calls += 1
        if self.gate is not None:
            self.gate.wait(20)
        time.sleep(self.seconds)
        if self.raise_ is not None:
            raise self.raise_
        if self.returns is not None:
            return self.returns
        return Fake("PASS").run(request, 0)


def body(stage="prep", case=CASE, **ctx):
    b = make_input(stage, case)
    b["context"].update(ctx)
    return b


def post(url, b, timeout=10):
    return httpx.post(f"{url}/run", json=b, timeout=timeout)


def parallel(fn, n):
    out, threads = [None] * n, []
    for i in range(n):
        threads.append(threading.Thread(target=lambda i=i: out.__setitem__(i, fn())))
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return out


# ------------------------------------------------------------ server-side de-duplication
def test_concurrent_duplicates_execute_once_and_all_get_the_same_answer(serve):
    h = Handler(seconds=0.5)
    url = serve(make_app("prep", h))
    b = body()
    responses = parallel(lambda: post(url, b), 6)
    assert h.calls == 1
    assert {r.status_code for r in responses} == {200}
    assert len({r.text for r in responses}) == 1, "byte-identical answers: same record, same content_hash"


def test_completed_request_is_replayed_from_cache(serve):
    h = Handler()
    url = serve(make_app("prep", h))
    b = body()
    first, again = post(url, b), post(url, copy.deepcopy(b))
    assert h.calls == 1 and first.status_code == again.status_code == 200 and first.json() == again.json()
    assert again.headers.get("idempotent-replay") == "true" and "idempotent-replay" not in first.headers


def test_same_key_with_a_different_body_is_409_and_not_executed(serve):
    h = Handler(seconds=0.3)
    url = serve(make_app("prep", h))
    b = body()
    changed = body(note="something else")
    running = threading.Thread(target=lambda: post(url, b))
    running.start()
    time.sleep(0.1)
    assert post(url, changed).status_code == 409, "while running"
    running.join()
    assert post(url, changed).status_code == 409, "after completion"
    assert h.calls == 1


def test_same_request_id_under_another_org_is_a_different_key(serve):
    h = Handler()
    url = serve(make_app("prep", h))
    a = body()
    b = body(case={**CASE, "org_id": "org_demo_bravo"})
    b["request_id"] = a["request_id"]
    assert post(url, a).status_code == 200 and post(url, b).status_code == 200
    assert h.calls == 2, "one tenant's cached answer is never served to another"


class Recording(IdempotencyCache):
    """Signals `duplicate` when a request arrives for a key that is still running (no timing guesses in tests)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.duplicate = threading.Event()

    def claim(self, key, body_hash):
        state, fut = super().claim(key, body_hash)
        if state == "running":
            self.duplicate.set()
        return state, fut


def wait_for_replay(url, b):
    for _ in range(200):
        r = post(url, b)
        if r.status_code == 200:
            return r
        time.sleep(0.05)
    return r


def test_wait_is_bounded_for_original_and_duplicate_then_the_cached_answer(serve):
    gate = threading.Event()
    h = Handler(gate=gate)
    url = serve(make_app("prep", h, idempotency=IdempotencyCache(wait_s=0.2)))
    b = body()
    first, dup = post(url, b), post(url, b)
    assert first.status_code == dup.status_code == 503 and dup.headers.get("retry-after"), "still running"
    gate.set()
    done = wait_for_replay(url, b)
    assert done.status_code == 200 and done.headers.get("idempotent-replay") == "true" and h.calls == 1


def test_a_caller_that_gives_up_does_not_cancel_or_repeat_the_work(serve):
    gate = threading.Event()
    h = Handler(gate=gate)
    url = serve(make_app("prep", h, idempotency=IdempotencyCache(wait_s=10)))
    b = body()
    with pytest.raises(httpx.ReadTimeout):
        post(url, b, timeout=0.3)  # the HTTP caller disconnects; the execution keeps going
    gate.set()
    done = wait_for_replay(url, b)
    assert done.status_code == 200 and h.calls == 1, "the abandoned call finished and was cached; never re-run"


def test_handler_exception_is_a_cached_pending_answer_not_a_stuck_entry(serve):
    h = Handler(raise_=RuntimeError("model API down"))
    url = serve(make_app("prep", h))
    b = body()
    first, again = post(url, b), post(url, b)
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert first.json()["status"] == "pending" and first.json()["error"]["code"] == "agent_exception"
    assert h.calls == 1


def test_worker_crash_sys_exit_does_not_leave_a_stuck_entry(serve):
    h = Handler(raise_=SystemExit(3))
    url = serve(make_app("prep", h))
    b = body()
    first = post(url, b, timeout=5)
    assert first.status_code == 200 and first.json()["status"] == "pending"
    assert post(url, b, timeout=5).status_code == 200 and h.calls == 1


def test_unserialisable_output_becomes_pending_not_a_permanent_500(serve):
    h = Handler(returns={"not": object()})
    url = serve(make_app("prep", h))
    r = post(url, body())
    assert r.status_code == 200 and r.json()["status"] == "pending"


def test_tenant_refusal_404_is_replayed_without_rerunning(serve):
    h = Handler(raise_=LookupError("no such unit in this org"))
    url = serve(make_app("prep", h))
    b = body()
    assert post(url, b).status_code == 404 and post(url, b).status_code == 404 and h.calls == 1


def test_invalid_input_is_422_before_any_entry_is_made(serve):
    h = Handler()
    url = serve(make_app("prep", h))
    assert post(url, {"request_id": "x", "nonsense": True}).status_code == 422 and h.calls == 0


# ------------------------------------------------------------ cache bounds (no unbounded growth, no stuck entries)
def test_completed_entries_expire_and_are_bounded_but_running_ones_are_never_evicted():
    cache = IdempotencyCache(ttl_s=0.2, max_entries=2)
    running = cache.claim(("o", "running"), "h")[1]
    for i in range(3):
        _, fut = cache.claim(("o", f"done{i}"), "h")
        cache.resolve(("o", f"done{i}"), fut, (200, {"i": i}))
    assert len(cache) <= 3 and ("o", "running") in cache.keys(), "bound applies to completed entries only"
    time.sleep(0.25)
    cache.claim(("o", "new"), "h")
    assert ("o", "done2") not in cache.keys() and ("o", "running") in cache.keys()
    assert not running.done()


def test_failed_resolution_drops_the_entry():
    cache = IdempotencyCache()
    _, fut = cache.claim(("o", "k"), "h")
    cache.drop(("o", "k"), fut, RuntimeError("cannot even build a pending output"))
    state, _ = cache.claim(("o", "k"), "h")
    assert state == "new", "a later call may execute again; nothing is stuck"


# ------------------------------------------------------------ capability reporting
def test_health_advertises_process_scoped_non_durable_idempotency(serve):
    url = serve(make_app("prep", Handler()))
    cap = httpx.get(f"{url}/health").json()["idempotency"]
    assert cap["supported"] is True and cap["key"] == ["subject.org_id", "request_id"]
    assert cap["scope"] == "process" and cap["durable"] is False and cap["ttl_s"] > 0


def test_idempotency_can_be_switched_off_and_then_is_not_advertised(serve, monkeypatch):
    monkeypatch.setenv("AGENT_IDEMPOTENCY", "off")
    h = Handler()
    url = serve(make_app("prep", h))
    assert httpx.get(f"{url}/health").json()["idempotency"] == {"supported": False}
    b = body()
    post(url, b), post(url, b)
    assert h.calls == 2


# ------------------------------------------------------------ orchestrator retry policy
def flow(timeout_s, retries=1):
    base = load_flow()
    return {**base, "defaults": {**base["defaults"], "timeout_s": timeout_s, "retries": retries}}


def run_prep_over_http(url, timeout_s, retries=1):
    """Run the workflow with only Prep over HTTP at `url`; every other stage is a local PASS."""
    clients = {s: Fake("PASS") for s in ("receiving", "pack", "returns", "recovery")}
    client = HttpClient({"stage": "prep", "url": url})
    clients["prep"] = client
    wf = run_workflow(CASE, flow(timeout_s, retries), MemoryStore(), clients)
    return wf, next(s for s in wf["stage_results"] if s["stage"] == "prep")


def test_ambiguous_timeout_is_retried_when_the_agent_is_idempotent_and_runs_once(serve):
    gate, cache = threading.Event(), Recording()
    h = Handler(gate=gate)
    url = serve(make_app("prep", h, idempotency=cache))

    def release_when_the_retry_arrives():
        cache.duplicate.wait(20)
        gate.set()

    threading.Thread(target=release_when_the_retry_arrives, daemon=True).start()
    try:
        wf, sr = run_prep_over_http(url, timeout_s=0.5, retries=2)
    finally:
        gate.set()
    assert cache.duplicate.is_set(), "the orchestrator retried after the ambiguous timeout"
    assert sr["state"] == "completed" and sr["attempts"] == 2
    assert h.calls == 1, "the retry was answered by the running execution, not a second model call"


def test_ambiguous_timeout_is_not_retried_when_the_agent_is_not_idempotent(serve, monkeypatch):
    monkeypatch.setenv("AGENT_IDEMPOTENCY", "off")
    gate = threading.Event()
    h = Handler(gate=gate)
    url = serve(make_app("prep", h))
    try:
        wf, sr = run_prep_over_http(url, timeout_s=0.3, retries=2)
    finally:
        gate.set()
    assert sr["attempts"] == 1 and sr["state"] == "error" and sr["error"]["code"] == "agent_timeout"
    assert any(t["event"] == "retry_skipped" for t in wf["transitions"])
    assert wf["status"] == "FAILED" and wf["final_outcome"]["outcome"] == "INCOMPLETE"
    assert h.calls == 1


def _server_error_app(advertise: bool, hits: list) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok", "stage": "prep", "contract_version": "1.0",
                **({"idempotency": {"supported": True}} if advertise else {})}

    @app.post("/run")
    def run():
        hits.append(1)
        return JSONResponse(status_code=500, content={"detail": "boom after doing work"})

    return app


@pytest.mark.parametrize("advertise,expected_hits", [(False, 1), (True, 3)])
def test_5xx_is_ambiguous_and_retried_only_for_idempotent_agents(serve, advertise, expected_hits):
    hits = []
    url = serve(_server_error_app(advertise, hits))
    wf, sr = run_prep_over_http(url, timeout_s=2, retries=2)
    assert len(hits) == expected_hits and sr["error"]["code"] == "agent_unavailable" and wf["status"] == "FAILED"


def test_connection_refused_is_always_retried_because_nothing_was_delivered():
    url = f"http://127.0.0.1:{free_port()}"  # nothing listening, and no /health to ask
    wf, sr = run_prep_over_http(url, timeout_s=1, retries=2)
    assert sr["attempts"] == 3 and sr["error"]["code"] == "agent_unavailable"
    assert not any(t["event"] == "retry_skipped" for t in wf["transitions"])


def test_health_failure_means_not_idempotent():
    assert HttpClient({"stage": "prep", "url": f"http://127.0.0.1:{free_port()}"}).idempotent is False
