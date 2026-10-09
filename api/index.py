"""Vercel serverless function entrypoint delegating to orchestration.api."""
from orchestration.api import app

__all__ = ["app"]
