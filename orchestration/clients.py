"""How the orchestrator talks to an agent: in-process (Python) or HTTP (any language)."""
from __future__ import annotations

import importlib
import json
import os
import threading
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


class AgentUnavailable(Exception):
    """Connection / 5xx: worth retrying.

    `ambiguous=True` means the request may have been delivered and acted on (read timeout, 5xx, connection dropped
    after sending). The orchestrator retries an ambiguous failure only against an agent that advertises
    idempotency; a failure to connect (never delivered) is always safe to retry (D-117)."""

    def __init__(self, message: str = "", *, ambiguous: bool = False):
        super().__init__(message)
        self.ambiguous = ambiguous


class AgentTimeout(AgentUnavailable):
    """No answer in time: worth retrying (if the agent is idempotent, when the request was delivered)."""


class AgentRejected(Exception):
    """4xx: the request or tenancy was refused. Retrying will not help."""


def load_manifest(stage: str) -> dict:
    return json.loads((ROOT / "agents" / stage / "agent.json").read_text(encoding="utf-8"))


class InProcClient:
    idempotent = True  # one in-flight execution per request_id in this process (D-112)

    def __init__(self, manifest: dict | None = None, handle=None):
        self.handle = handle or importlib.import_module(manifest["module"]).handle
        self._lock = threading.Lock()
        self._inflight: dict[str, tuple[threading.Thread, dict]] = {}

    def run(self, request: dict, timeout_s: float) -> dict:
        """Call handle() on a worker thread and stop waiting after timeout_s (D-110, D-111, D-112).

        * The agent gets a deep COPY of the request, and the orchestrator gets a copy of the answer: an in-process
          agent (or an orphaned thread) shares no mutable object with workflow state or stored evidence.
        * At most ONE execution per request_id is in flight. A retry after a timeout re-joins the running execution
          instead of starting a duplicate (no second model call / side effect). A new request_id (resume -> ":r2")
          starts a new execution.
        * Python cannot kill a thread: a hung agent keeps running as a daemon. If it never finishes inside a later
          attempt's window its answer is discarded; nothing it does afterwards reaches the orchestrator.
        """
        key = request["request_id"]
        with self._lock:
            for k in [k for k, (t, _) in self._inflight.items() if k != key and not t.is_alive()]:
                del self._inflight[k]  # abandoned executions that have since finished: their answers are discarded
            worker, box = self._inflight.get(key, (None, None))
            if worker is None:
                box = {}
                snapshot = json.loads(json.dumps(request))
                worker = threading.Thread(target=self._call, args=(snapshot, box),
                                          name=f"agent-{request.get('stage')}", daemon=True)
                self._inflight[key] = (worker, box)
                worker.start()
        worker.join(timeout_s)
        if worker.is_alive():
            raise AgentTimeout(f"in-process agent did not answer within {timeout_s}s")
        with self._lock:
            self._inflight.pop(key, None)
        if isinstance(box.get("exc"), LookupError):
            raise AgentRejected(str(box["exc"])) from box["exc"]
        if "exc" in box:
            raise box["exc"]
        return json.loads(json.dumps(box["out"]))

    def _call(self, request: dict, box: dict) -> None:
        try:
            box["out"] = self.handle(request)
        except Exception as exc:  # handed back to the orchestrator thread
            box["exc"] = exc
        except BaseException as exc:  # sys.exit() in an agent must not stop the orchestrator: it is an agent crash
            box["exc"] = RuntimeError(f"agent raised {type(exc).__name__}: {exc}")


class HttpClient:
    def __init__(self, manifest: dict):
        env = f"{manifest['stage'].upper()}_URL"
        self.url = os.environ.get(env, manifest["url"]).rstrip("/")
        self._idempotent: bool | None = None

    def run(self, request: dict, timeout_s: float) -> dict:
        try:
            resp = httpx.post(f"{self.url}/run", json=request, timeout=timeout_s)
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout) as exc:
            # Never connected (nothing listening, host down): the request was NOT delivered. On Windows a refused
            # localhost connection is retried by the OS and surfaces as a connect timeout, so classify by phase.
            raise AgentUnavailable(f"{type(exc).__name__}: {exc}") from exc
        except httpx.TimeoutException as exc:  # sent, but no answer in time: the agent may still be working
            raise AgentTimeout(f"{type(exc).__name__}: {exc}", ambiguous=True) from exc
        except httpx.HTTPError as exc:  # broke after sending (read error, protocol error): may have been acted on
            raise AgentUnavailable(f"{type(exc).__name__}: {exc}", ambiguous=True) from exc
        if 400 <= resp.status_code < 500:
            raise AgentRejected(f"HTTP {resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 500:  # delivered; the agent may have done the work before failing
            raise AgentUnavailable(f"HTTP {resp.status_code}: {resp.text[:300]}", ambiguous=True)
        return resp.json()

    def health(self) -> dict:
        return httpx.get(f"{self.url}/health", timeout=5).json()

    @property
    def idempotent(self) -> bool:
        """Does the agent advertise request_id de-duplication (`/health` -> idempotency.supported is true)?
        Asked once per client, only when an ambiguous failure needs the answer. Unreachable / unknown -> False."""
        if self._idempotent is None:
            try:
                self._idempotent = (self.health().get("idempotency") or {}).get("supported") is True
            except Exception:
                self._idempotent = False
        return self._idempotent


def client_for(stage: str):
    manifest = load_manifest(stage)
    mode = os.environ.get("ORCH_MODE") or manifest["mode"]
    return InProcClient(manifest) if mode == "inproc" else HttpClient(manifest)
