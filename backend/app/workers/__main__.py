"""CLI entry point for running ARQ worker independently.

Usage:
    python -m app.workers
"""

from typing import Any, cast

from arq.worker import run_worker

from app.workers.settings import WorkerSettings

if __name__ == "__main__":
    run_worker(cast(Any, WorkerSettings))
