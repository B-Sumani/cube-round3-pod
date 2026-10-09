"""Pack Manager: agent entry point.

Exposes handle(agent_input: dict) -> dict conforming to CUBE Agent Contract v1.
Run standalone: uvicorn agents.pack.app:app --port 8103
"""
from __future__ import annotations

from fastapi import HTTPException

from shared.utils.schema import errors
from shared.utils.server import make_app

from agents.pack.engine import AGENT_ID, STAGE, run_pack_pipeline


def handle(agent_input: dict) -> dict:
    """Entry point for the orchestrator (inproc or HTTP)."""
    problems = (
        errors("agent-input", agent_input)
        if isinstance(agent_input, dict)
        else ["agent_input must be a dict"]
    )
    if problems or not isinstance(agent_input, dict) or agent_input.get("stage") != STAGE:
        raise HTTPException(
            status_code=422,
            detail=problems or [f"stage must be '{STAGE}'"],
        )
    return run_pack_pipeline(agent_input)


app = make_app(STAGE, handle)
