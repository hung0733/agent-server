from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "backup_production_data.py"
_SPEC = importlib.util.spec_from_file_location("backup_production_data", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
backup_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(backup_module)


def test_build_docker_pg_dump_command_uses_container_exec():
    command = backup_module._build_docker_pg_dump_command(
        host="localhost",
        port="5432",
        user="agentserver",
        password="secret",
        database="agentserver",
    )

    assert command == [
        "docker",
        "exec",
        "-e",
        "PGPASSWORD=secret",
        "agent-postgres",
        "pg_dump",
        "--format=custom",
        "--host",
        "localhost",
        "--port",
        "5432",
        "--username",
        "agentserver",
        "agentserver",
    ]


def test_main_writes_backup_using_docker_exec(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(backup_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "agentserver")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_DB", "agentserver")

    calls = []

    def fake_run(command, check, stdout):
        calls.append(command)
        stdout.write(b"backup")

    monkeypatch.setattr(backup_module.subprocess, "run", fake_run)

    exit_code = backup_module.main()

    assert exit_code == 0
    assert len(calls) == 1
    backup_files = list((tmp_path / "backups").glob("production_backup_agentserver_*.dump"))
    assert len(backup_files) == 1
    assert backup_files[0].read_bytes() == b"backup"
