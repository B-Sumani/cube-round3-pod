"""Where workflow state and evidence live. Two implementations of one tiny interface.

MemoryStore: tests and library use. FileStore: the CLI and API (JSON files under out/).
Swap in a database by implementing the same four methods. Evidence is IMMUTABLE: a record_id, once written,
can only be written again with identical content.

TENANCY: every method takes an optional `org_id`. When it is given (the orchestrator, API and CLI always give
it), the store refuses to read or write anything that belongs to another organisation and raises
`TenantViolation`. Isolation is enforced here as well as in the orchestrator, so one bug in one layer cannot
leak another org's data. `org_id=None` is an unscoped, admin-only read kept for tests and offline scripts.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

# How long a caller waits for another caller to finish advancing the same workflow (D-115). A full advance is bounded
# by stages x (retries + 1) x timeout_s (300 s with the default flow), so the default waits that long and then fails.
LOCK_TIMEOUT_S = float(os.environ.get("ORCH_LOCK_TIMEOUT_S", "300"))


class EvidenceConflict(Exception):
    pass


class WorkflowBusy(RuntimeError):
    """Another caller held this workflow's lock for longer than LOCK_TIMEOUT_S. Nothing was changed; retry later."""


class TenantViolation(LookupError):
    """A read or write crossed an organisation boundary. A LookupError, so APIs answer 404 (never reveal it exists)."""


def _record_org(record: dict) -> str | None:
    return (record.get("subject") or {}).get("org_id")


def _check(kind: str, key: str, owner: str | None, org_id: str | None) -> None:
    if org_id is not None and owner != org_id:
        raise TenantViolation(f"{kind} {key} is not visible to {org_id}")


class MemoryStore:
    def __init__(self) -> None:
        self.workflows: dict[str, dict] = {}
        self.evidence: dict[str, dict] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    # --- per-workflow mutual exclusion (D-115) ----------------------------------------------------------------
    @contextlib.contextmanager
    def workflow_lock(self, workflow_id: str):
        """Hold while loading, advancing and saving one workflow. Re-entrant within a thread; other threads (and,
        for FileStore, other processes) wait up to LOCK_TIMEOUT_S, then WorkflowBusy. Other workflows never wait."""
        with self._locks_guard:
            lock = self._locks.setdefault(workflow_id, threading.RLock())
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        if not lock.acquire(timeout=LOCK_TIMEOUT_S):
            raise WorkflowBusy(f"workflow {workflow_id} is being advanced by another caller")
        try:
            with self._process_lock(workflow_id, deadline):
                yield
        finally:
            lock.release()

    @contextlib.contextmanager
    def _process_lock(self, workflow_id: str, deadline: float):
        yield  # a MemoryStore lives in one process: the thread lock is enough

    # --- raw access (override these four in a subclass; tenancy is applied on top) -------------------------
    def _read_workflow(self, workflow_id: str) -> dict | None:
        wf = self.workflows.get(workflow_id)
        return json.loads(json.dumps(wf)) if wf else None

    def _write_workflow(self, wf: dict) -> None:
        self.workflows[wf["workflow_id"]] = json.loads(json.dumps(wf))

    def _read_evidence(self, record_id: str) -> dict | None:
        rec = self.evidence.get(record_id)
        return json.loads(json.dumps(rec)) if rec else None  # callers get a copy: stored evidence is never shared

    def _create_evidence(self, record: dict) -> bool:
        """Atomically create the record. False if the id already exists (nothing written) (D-116)."""
        with self._locks_guard:
            if record["record_id"] in self.evidence:
                return False
            self.evidence[record["record_id"]] = json.loads(json.dumps(record))
            return True

    # --- tenant-scoped interface -----------------------------------------------------------------------------
    def load_workflow(self, workflow_id: str, org_id: str | None = None) -> dict | None:
        wf = self._read_workflow(workflow_id)
        if wf is not None:
            _check("workflow", workflow_id, wf.get("org_id"), org_id)
        return wf

    def save_workflow(self, wf: dict, org_id: str | None = None) -> None:
        _check("workflow", wf["workflow_id"], wf.get("org_id"), org_id)
        existing = self._read_workflow(wf["workflow_id"])
        if existing is not None and existing.get("org_id") != wf.get("org_id"):
            raise TenantViolation(f"workflow {wf['workflow_id']} belongs to another organisation")
        self._write_workflow(wf)

    def get_evidence(self, record_id: str, org_id: str | None = None) -> dict | None:
        rec = self._read_evidence(record_id)
        if rec is not None:
            _check("evidence", record_id, _record_org(rec), org_id)
        return rec

    def put_evidence(self, record: dict, org_id: str | None = None) -> None:
        """Create-once. Identical content again is a no-op; different content raises EvidenceConflict; an id owned
        by another org raises TenantViolation. Creation is atomic, so two racing writers can never both win (D-116)."""
        _check("evidence", record["record_id"], _record_org(record), org_id)
        existing = self._read_evidence(record["record_id"])
        if existing is None:
            if self._create_evidence(record):
                return
            existing = self._read_evidence(record["record_id"])  # lost the race: judge against the winner
        if _record_org(existing) != _record_org(record):
            raise TenantViolation(f"evidence {record['record_id']} belongs to another organisation")
        if existing["content_hash"] != record["content_hash"]:
            raise EvidenceConflict(f"{record['record_id']} already exists with different content; evidence is immutable")


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _filename(key: str) -> str:
    """Ids come from agents: never let one become a path (../, /, backslash, drive letters)."""
    if not _SAFE_ID.match(key) or ".." in key:
        raise ValueError(f"unsafe id for file storage: {key!r}")
    return f"{key}.json"


def _os_lock(fh) -> None:
    fh.seek(0)
    if os.name == "nt":
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _os_unlock(fh) -> None:
    fh.seek(0)
    if os.name == "nt":
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _replace(src: Path, dst: Path, attempts: int = 20) -> None:
    """os.replace, retried briefly on Windows, where a concurrent reader (GET /workflows) holding dst open makes the
    rename fail with PermissionError. Writers are already serialised by the workflow lock."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.01 * (i + 1))


class FileStore(MemoryStore):
    def __init__(self, root: str | Path | None = None) -> None:
        super().__init__()
        self.root = Path(root or os.environ.get("OUT_DIR", "out"))
        (self.root / "workflows").mkdir(parents=True, exist_ok=True)
        (self.root / "evidence").mkdir(parents=True, exist_ok=True)

    def _read_workflow(self, workflow_id: str) -> dict | None:
        p = self.root / "workflows" / _filename(workflow_id)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _write_workflow(self, wf: dict) -> None:
        p = self.root / "workflows" / _filename(wf["workflow_id"])
        tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex}.tmp")  # unique per write: writers never share a temp file
        tmp.write_text(json.dumps(wf, indent=2), encoding="utf-8")
        _replace(tmp, p)  # atomic: a crash never leaves half a workflow

    @contextlib.contextmanager
    def _process_lock(self, workflow_id: str, deadline: float):
        """OS advisory lock on out/locks/<workflow_id>.lock: the CLI and the API (separate processes) share out/.
        Released by the OS if the process dies, so a crash never leaves a stale lock. Lock files are kept (deleting
        them would race with a waiter); there is one small file per workflow."""
        (self.root / "locks").mkdir(exist_ok=True)
        with open(self.root / "locks" / f"{_filename(workflow_id)}.lock", "a+b") as fh:
            while True:
                try:
                    _os_lock(fh)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise WorkflowBusy(f"workflow {workflow_id} is being advanced by another process") from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                _os_unlock(fh)

    def _read_evidence(self, record_id: str) -> dict | None:
        p = self.root / "evidence" / _filename(record_id)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _create_evidence(self, record: dict) -> bool:
        """Write the full record to a unique temp file, then hard-link it into place (D-116). link() fails if the name
        exists, so creation is atomic across threads AND processes, and a reader never sees a half-written record.
        Filesystems without hard links fall back to exclusive create ("x"): still never overwrites."""
        final = self.root / "evidence" / _filename(record["record_id"])
        body = json.dumps(record, indent=2)
        tmp = final.with_name(f".{final.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(body, encoding="utf-8")
        try:
            os.link(tmp, final)
            return True
        except FileExistsError:
            return False
        except OSError:  # no hard-link support here
            try:
                with open(final, "x", encoding="utf-8") as fh:
                    fh.write(body)
                return True
            except FileExistsError:
                return False
        finally:
            tmp.unlink(missing_ok=True)
