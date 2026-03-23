# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
source .venv/bin/activate
pip install -r requirements.txt

# Tests
python -m pytest tests/ -v
python -m pytest tests/unit/ -v
python -m pytest tests/integration/ -v
python -m pytest path/to/test_file.py::TestClass::test_method -v
python -m pytest --cov=src/ tests/ --cov-report=html

# Code quality
flake8 src/ --show-source
black src/ tests/
isort src/ tests/
mypy src/ --strict

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "message"
```

## Architecture

**Agent Server** is a multi-tenant agent orchestration platform built on Python 3.12, LangGraph, PostgreSQL, and Qdrant.

### Key Modules

- **`src/simplemem_cross_lite/`** — Cross-session memory system. `SessionManager` orchestrates lifecycle; `EventCollector` is a write-behind buffer; `ObservationExtractor` produces structured observations. Storage is abstracted: `postgres.py` (session data) and `qdrant.py` (vector store).

- **`src/db/`** — Database layer with SQLAlchemy 2.x async. Organized into:
  - `entity/` — ORM models (16 files)
  - `dao/` — Data Access Objects (20 files)
  - `dto/` — Data Transfer Objects (15 files)
  - `types.py` — StrEnum definitions for all status/kind fields
  - `checkpoint.py` — LangGraph checkpoint integration

- **`src/tools/db_pool.py`** — Global async PostgreSQL connection pool (`DatabasePool`). Use the singleton pattern for pool access.

- **`src/graph/`** — LangGraph agent graph definitions (in development).

### Patterns

- DAO/DTO separation: DAOs handle DB access; DTOs handle serialization
- Async throughout with `asyncio` and `asyncpg`
- Multi-tenant isolation via `tenant_id` on all entities
- UUID v4 primary keys; soft deletes via `is_active`
- JSONB for flexible metadata storage

## Code Style

- Line length: 88–100 characters
- Docstrings: Google-style or NumPy format
- Imports: stdlib → third-party → local, blank lines between groups
- Use specific exception types; raise on missing env vars (no defaults)
- Async only where genuine parallelism benefit exists

## Environment Variables

All required; no defaults — missing vars must raise at startup. See `.env.example` for the full list (PostgreSQL, Qdrant, pool sizing, agent limits).

## i18n

Default locale is `zh-HK` (香港繁體中文). All user-facing strings must use `gettext` or equivalent i18n library. Store translations in language resource files.

## Commit Messages

Imperative tone: `Add feature`, `Fix bug`, `Refactor component`. Tag breaking changes as `BREAKING:` with migration notes.
