"""In-memory idempotency for agent servers: one execution per (org_id, request_id) (docs/decisions.md D-117).

Scope, honestly: ONE PROCESS, IN MEMORY. Entries do not survive a restart and are not shared between uvicorn workers
or replicas. A retry that lands on another process, after a restart, or after `ttl_s` executes again. Run an agent
with a single worker if it relies on this, or switch it off (AGENT_IDEMPOTENCY=off) so the orchestrator does not
retry ambiguous failures against it.

States of a key:  running (future not done) -> completed (future holds (status, body), kept for ttl_s) -> evicted.
A running entry is never evicted (dropping it would let a retry start a duplicate). It cannot get stuck: the worker
that executes the handler always resolves or drops it, whatever happens to the HTTP request that started it.
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future


class KeyReused(Exception):
    """Same (org_id, request_id), different request body: a client bug, answered 409."""


class IdempotencyCache:
    def __init__(self, ttl_s: float | None = None, max_entries: int | None = None, wait_s: float | None = None):
        env = os.environ.get
        self.ttl_s = float(ttl_s if ttl_s is not None else env("AGENT_IDEMPOTENCY_TTL_S", "900"))
        self.max_entries = int(max_entries if max_entries is not None else env("AGENT_IDEMPOTENCY_MAX_ENTRIES", "1000"))
        # How long a duplicate waits for the running execution before 503 + Retry-After. Keep it below the
        # orchestrator's timeout_s (default 30 s) so the waiting caller gets an answer rather than its own timeout.
        self.wait_s = float(wait_s if wait_s is not None else env("AGENT_IDEMPOTENCY_WAIT_S", "25"))
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple, list] = OrderedDict()  # key -> [body_hash, future, completed_at|None]

    def __len__(self) -> int:
        return len(self._entries)

    def keys(self) -> list[tuple]:
        with self._lock:
            return list(self._entries)

    def capability(self) -> dict:
        return {"supported": True, "key": ["subject.org_id", "request_id"], "scope": "process", "durable": False,
                "ttl_s": self.ttl_s, "wait_s": self.wait_s}

    def claim(self, key: tuple, body_hash: str) -> tuple[str, Future]:
        """("new", future): the caller must execute and then resolve()/drop(). ("running"|"completed", future): wait
        on / read the existing one. Raises KeyReused if the key was seen with a different body."""
        with self._lock:
            self._purge()
            entry = self._entries.get(key)
            if entry is not None:
                if entry[0] != body_hash:
                    raise KeyReused(f"request_id {key[1]!r} was already used with a different request body")
                return ("completed" if entry[1].done() else "running"), entry[1]
            future: Future = Future()
            self._entries[key] = [body_hash, future, None]
            return "new", future

    def resolve(self, key: tuple, future: Future, response: tuple[int, object]) -> None:
        """The execution finished with a final HTTP answer (any status): cache it for ttl_s."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[1] is future:
                entry[2] = time.monotonic()
                self._entries.move_to_end(key)
        future.set_result(response)

    def drop(self, key: tuple, future: Future, exc: BaseException) -> None:
        """The execution could not even produce an answer: forget the key (a later call may run again) and wake
        any waiter with the error."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[1] is future:
                del self._entries[key]
        if not future.done():
            future.set_exception(exc)

    def _purge(self) -> None:
        """Expire completed entries older than ttl_s; then, over max_entries, evict the oldest completed ones."""
        now = time.monotonic()
        for k in [k for k, e in self._entries.items() if e[2] is not None and now - e[2] > self.ttl_s]:
            del self._entries[k]
        completed = [k for k, e in self._entries.items() if e[2] is not None]
        for k in completed[: max(0, len(self._entries) - self.max_entries)]:
            del self._entries[k]


def from_env() -> IdempotencyCache | None:
    """AGENT_IDEMPOTENCY=off disables de-duplication AND stops advertising it (the orchestrator then does not retry
    ambiguous failures against this agent)."""
    if os.environ.get("AGENT_IDEMPOTENCY", "on").strip().lower() in ("off", "0", "false", "no"):
        return None
    return IdempotencyCache()
