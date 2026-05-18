"""Console entry points for Arq workers."""

from __future__ import annotations

import logging

from arq.worker import run_worker as arq_run_worker

from ingestor.arq_worker import WorkerSettings


def run_worker() -> None:
    logging.basicConfig(level=logging.INFO)
    arq_run_worker(WorkerSettings)


if __name__ == "__main__":
    run_worker()
