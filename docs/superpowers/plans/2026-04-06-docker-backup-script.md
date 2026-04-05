# Docker Backup Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `scripts/backup_production_data.py` run PostgreSQL backup through a Docker `postgres:17` image instead of the host `pg_dump` binary.

**Architecture:** Keep the script as a small CLI entrypoint, but extract Docker command construction into a helper so command generation and error mapping can be tested without touching a real database. Use the existing environment loading flow and keep output behavior unchanged: create `backups/`, write a timestamped `.dump` file, print the path on success.

**Tech Stack:** Python 3.12, `subprocess`, `pathlib`, `pytest`, `unittest.mock`

---

### Task 1: Add failing tests for Docker-backed backup execution

**Files:**
- Create: `tests/unit/test_backup_production_data.py`
- Modify: `scripts/backup_production_data.py`
- Test: `tests/unit/test_backup_production_data.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import backup_production_data as backup_module


def test_build_backup_command_uses_docker_postgres_image(tmp_path: Path) -> None:
    backup_path = tmp_path / "production_backup_agentserver_20260406T010000Z.dump"

    command, env = backup_module._build_backup_command(
        host="db.example.internal",
        port="5432",
        user="agentserver",
        password="secret",
        database="agentserver",
        backup_path=backup_path,
    )

    assert command == [
        "docker",
        "run",
        "--rm",
        "-e",
        "PGPASSWORD=secret",
        "-v",
        f"{backup_path.parent.resolve()}:/backups",
        "postgres:17",
        "pg_dump",
        "--format=custom",
        "--file",
        f"/backups/{backup_path.name}",
        "--host",
        "db.example.internal",
        "--port",
        "5432",
        "--username",
        "agentserver",
        "agentserver",
    ]
    assert env == {}


def test_main_reports_missing_docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "db.example.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "agentserver")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_DB", "agentserver")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(backup_module, "load_dotenv", lambda: None)

    def _raise(*_args, **_kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(backup_module.subprocess, "run", _raise)

    with pytest.raises(RuntimeError, match="Docker is not installed or not in PATH"):
        backup_module.main()


def test_main_reports_docker_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "db.example.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "agentserver")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_DB", "agentserver")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(backup_module, "load_dotenv", lambda: None)

    def _raise(*_args, **_kwargs):
        raise subprocess.CalledProcessError(returncode=125, cmd=["docker"])

    monkeypatch.setattr(backup_module.subprocess, "run", _raise)

    with pytest.raises(RuntimeError, match="Docker pg_dump failed with exit code 125"):
        backup_module.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_backup_production_data.py -v`
Expected: FAIL because `_build_backup_command` does not exist and the script still invokes host `pg_dump`.

- [ ] **Step 3: Write minimal implementation**

```python
def _build_backup_command(
    *,
    host: str,
    port: str,
    user: str,
    password: str,
    database: str,
    backup_path: Path,
) -> tuple[list[str], dict[str, str]]:
    backup_dir = backup_path.parent.resolve()
    container_backup_path = f"/backups/{backup_path.name}"
    command = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"PGPASSWORD={password}",
        "-v",
        f"{backup_dir}:/backups",
        "postgres:17",
        "pg_dump",
        "--format=custom",
        "--file",
        container_backup_path,
        "--host",
        host,
        "--port",
        port,
        "--username",
        user,
        database,
    ]
    return command, {}


command, env = _build_backup_command(
    host=host,
    port=port,
    user=user,
    password=password,
    database=database,
    backup_path=backup_path,
)

try:
    subprocess.run(command, check=True, env=env)
except FileNotFoundError as exc:
    raise RuntimeError("Docker is not installed or not in PATH") from exc
except subprocess.CalledProcessError as exc:
    raise RuntimeError(f"Docker pg_dump failed with exit code {exc.returncode}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_backup_production_data.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/backup_production_data.py tests/unit/test_backup_production_data.py
git commit -m "Use Docker pg_dump for backups"
```

### Task 2: Verify the script still creates a backup path in the real workspace flow

**Files:**
- Modify: `scripts/backup_production_data.py`
- Test: `tests/unit/test_backup_production_data.py`

- [ ] **Step 1: Write the failing test**

```python
def test_main_creates_backups_directory_and_prints_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "db.example.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "agentserver")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_DB", "agentserver")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(backup_module, "load_dotenv", lambda: None)

    recorded = {}

    def _fake_run(command, check, env):
        recorded["command"] = command
        recorded["check"] = check
        recorded["env"] = env

    monkeypatch.setattr(backup_module.subprocess, "run", _fake_run)

    result = backup_module.main()

    out = capsys.readouterr().out.strip()
    assert result == 0
    assert out.startswith("backups/production_backup_agentserver_")
    assert out.endswith(".dump")
    assert (tmp_path / "backups").exists()
    assert recorded["check"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_backup_production_data.py::test_main_creates_backups_directory_and_prints_path -v`
Expected: FAIL until the script exposes the Docker-backed flow while preserving the printed relative path.

- [ ] **Step 3: Write minimal implementation**

```python
backup_dir = Path("backups")
backup_dir.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup_path = backup_dir / f"production_backup_{database}_{timestamp}.dump"

command, env = _build_backup_command(
    host=host,
    port=port,
    user=user,
    password=password,
    database=database,
    backup_path=backup_path,
)

subprocess.run(command, check=True, env=env)
print(backup_path)
return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_backup_production_data.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/backup_production_data.py tests/unit/test_backup_production_data.py
git commit -m "Test Docker-based backup script"
```

### Task 3: Final verification

**Files:**
- Modify: `scripts/backup_production_data.py`
- Test: `tests/unit/test_backup_production_data.py`

- [ ] **Step 1: Run the focused unit test suite**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_backup_production_data.py -v`
Expected: PASS

- [ ] **Step 2: Run the script once against the real environment**

Run: `source .venv/bin/activate && python scripts/backup_production_data.py`
Expected: prints `backups/production_backup_<db>_<timestamp>.dump` and exits 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/backup_production_data.py tests/unit/test_backup_production_data.py
git commit -m "Use Docker pg_dump for backup script"
```
