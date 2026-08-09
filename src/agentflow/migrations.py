"""Checksum-verified PostgreSQL migration runner."""

from __future__ import annotations

import hashlib
from pathlib import Path

import asyncpg

from agentflow.errors import ConflictError, DependencyUnavailableError


def default_migrations_directory() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "migrations"
        if candidate.is_dir():
            return candidate
    return Path.cwd() / "migrations"


async def run_migrations(*, dsn: str, directory: Path | None = None) -> list[str]:
    migrations_directory = (directory or default_migrations_directory()).resolve()
    files = sorted(migrations_directory.glob("[0-9]*.sql"))
    if not files:
        raise FileNotFoundError(f"no SQL migrations found in {migrations_directory}")
    try:
        connection = await asyncpg.connect(dsn)
    except (OSError, asyncpg.PostgresError) as exc:
        raise DependencyUnavailableError("PostgreSQL migration connection failed") from exc
    applied: list[str] = []
    try:
        await connection.execute("SELECT pg_advisory_lock(hashtext('agentflow-migrations'))")
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version text PRIMARY KEY,
                checksum_sha256 text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        for path in files:
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            existing = await connection.fetchval(
                "SELECT checksum_sha256 FROM schema_migrations WHERE version = $1",
                path.name,
            )
            if existing is not None:
                if existing != checksum:
                    raise ConflictError(
                        "an applied migration has changed",
                        details={"migration": path.name},
                    )
                continue
            async with connection.transaction():
                await connection.execute(sql)
                await connection.execute(
                    "INSERT INTO schema_migrations (version, checksum_sha256) VALUES ($1, $2)",
                    path.name,
                    checksum,
                )
            applied.append(path.name)
    finally:
        try:
            await connection.execute("SELECT pg_advisory_unlock(hashtext('agentflow-migrations'))")
        finally:
            await connection.close()
    return applied
