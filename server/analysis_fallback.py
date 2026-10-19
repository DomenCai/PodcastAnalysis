"""Persist the Kimi circuit breaker across tasks and manager restarts."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from server.analysis_runner import AnalysisConfig, AnalysisError
from server.processing_lock import processing_lock

COOLDOWN_SECONDS = 3600
ROOT = Path(__file__).resolve().parents[1]


def _state_path() -> Path:
    return Path(os.getenv("PODCAST_DATA_DIR", ROOT / "data")).expanduser().resolve() / "analysis-fallback.json"


def cooldown_status() -> dict:
    path = _state_path()
    with processing_lock(path.with_suffix(".lock")):
        until = 0.0
        if path.exists() or path.is_symlink():
            try:
                if path.is_symlink():
                    raise ValueError()
                state = json.loads(path.read_text())
                until = state["cooldown_until"]
                if type(until) not in (int, float) or not math.isfinite(until) or not 0 <= until <= 253402300799:
                    raise ValueError()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise AnalysisError("分析备用状态损坏，拒绝覆盖", category="config") from exc
    remaining = max(0, math.ceil(until - time.time()))
    return {"active": remaining > 0, "remaining_seconds": remaining,
            "cooldown_until": datetime.fromtimestamp(until, UTC).isoformat() if until else None}


def start_cooldown() -> None:
    path = _state_path()
    with processing_lock(path.with_suffix(".lock")):
        descriptor, name = tempfile.mkstemp(prefix=".analysis-fallback-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump({"version": 1, "cooldown_until": time.time() + COOLDOWN_SECONDS}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def codex_config(config: AnalysisConfig) -> AnalysisConfig:
    return replace(config, backend="codex", model="gpt-6.1-sol", thinking="high",
                   reminder_interval=0, fallback_backend=None)
