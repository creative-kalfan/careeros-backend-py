"""Entry point for the CareerOS ARQ worker.

Run with:
    python -m arq app.workers.main
    python -m arq app.workers.settings.WorkerSettings
"""

from __future__ import annotations

from arq.worker import run_worker

from app.workers.settings import WorkerSettings

if __name__ == "__main__":
    run_worker(WorkerSettings)
