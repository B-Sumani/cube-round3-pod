"""Pack Manager: agent entry point.

Exposes handle(request: dict) -> dict conforming to CUBE Agent Contract v1.
Run standalone: uvicorn agents.pack.app:app --port 8103
"""
from __future__ import annotations

from shared.utils.server import make_app

from agents.pack.engine import AGENT_ID, STAGE, run_pack_pipeline


def handle(request: dict) -> dict:
    """Entry point for the orchestrator (inproc or HTTP)."""
    return run_pack_pipeline(request)


app = make_app(STAGE, handle)
