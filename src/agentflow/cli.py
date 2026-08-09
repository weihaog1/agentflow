"""Console entry points for the API, worker, and migration runner."""

from __future__ import annotations

import argparse
import asyncio
import signal
from collections.abc import Sequence
from pathlib import Path

import structlog
import uvicorn

from agentflow.api.app import create_app
from agentflow.config import Settings, get_settings
from agentflow.container import build_container
from agentflow.logging import configure_logging
from agentflow.migrations import run_migrations

logger = structlog.get_logger(__name__)


def api(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the AgentFlow FastAPI server.")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    settings = get_settings()
    uvicorn.run(
        create_app(settings),
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_level=settings.log_level.lower(),
    )


async def _worker_main(settings: Settings) -> None:
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)
    container = await build_container(settings)
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, lambda: asyncio.create_task(container.worker.stop()))
    try:
        await container.worker.run_forever()
    finally:
        await container.close()


def worker(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the AgentFlow ingestion worker.")
    parser.parse_args(argv)
    asyncio.run(_worker_main(get_settings()))


async def _migrate_main(settings: Settings, directory: Path | None) -> None:
    if settings.database_url is None:
        raise SystemExit("AGENTFLOW_DATABASE_URL is required for migrations")
    applied = await run_migrations(
        dsn=settings.database_url.get_secret_value(),
        directory=directory,
    )
    logger.info("migrations_completed", applied=applied, count=len(applied))


def migrate(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apply checksum-verified AgentFlow migrations.")
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)
    asyncio.run(_migrate_main(settings, args.directory))
