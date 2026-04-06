#!/usr/bin/env python3
"""Create a PostgreSQL backup before running tests."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set")
    return value


def _build_docker_pg_dump_command(
    *,
    host: str,
    port: str,
    user: str,
    password: str,
    database: str,
) -> list[str]:
    return [
        "docker",
        "exec",
        "-e",
        f"PGPASSWORD={password}",
        "agent-postgres",
        "pg_dump",
        "--format=custom",
        "--host",
        host,
        "--port",
        port,
        "--username",
        user,
        database,
    ]


def main() -> int:
    load_dotenv()

    host = _require_env("POSTGRES_HOST")
    port = _require_env("POSTGRES_PORT")
    user = _require_env("POSTGRES_USER")
    password = _require_env("POSTGRES_PASSWORD")
    database = _require_env("POSTGRES_DB")

    backup_dir = Path("backups")
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"production_backup_{database}_{timestamp}.dump"

    command = _build_docker_pg_dump_command(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    )

    try:
        with backup_path.open("wb") as backup_file:
            subprocess.run(command, check=True, stdout=backup_file)
    except FileNotFoundError as exc:
        raise RuntimeError("docker is not installed or not in PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"docker pg_dump failed with exit code {exc.returncode}"
        ) from exc

    print(backup_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
