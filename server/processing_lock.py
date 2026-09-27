"""Cross-process lock for the local model pipeline (Mac/Linux).

CLI entrypoints submit to the service. This extra lock serializes pipeline
execution even if a separate local process explicitly uses JobManager directly.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import fcntl


@contextmanager
def processing_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
