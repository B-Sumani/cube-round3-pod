"""Configuration module for Pack Manager rules and thresholds.

Thresholds are kept in configuration rather than scattered across code.
Pure standard library dataclass with zero external dependencies.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PackConfig:
    count_confidence_threshold: float = 0.70
    identity_confidence_threshold: float = 0.75
    total_timeout_budget: float = 15.0
    version: str = "v1.0.0"

    @classmethod
    def from_env(cls) -> PackConfig:
        return cls(
            count_confidence_threshold=float(os.getenv("CONF_COUNT_THRESHOLD", "0.70")),
            identity_confidence_threshold=float(os.getenv("CONF_IDENTITY_THRESHOLD", "0.75")),
            total_timeout_budget=float(os.getenv("PACK_TIMEOUT_BUDGET", "15.0")),
            version=os.getenv("PACK_CONFIG_VERSION", "v1.0.0"),
        )


DEFAULT_CONFIG = PackConfig.from_env()
