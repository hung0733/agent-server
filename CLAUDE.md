# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Assistant Communication Language

- Respond to the user in Hong Kong Traditional Chinese (`zh-HK`) by default.
- Switch to another language only when the user explicitly requests it.

## Language and Framework Requirements

- **Primary Language**: Python 3.12
- **Virtual Environment**: Use `.venv` directory with activation via `source .venv/bin/activate`
- **Dependency Management**: Standard Python practices using `requirements.txt`, `pyproject.toml` or `setup.py`
- **Standard Library**: Use whenever possible; follow Python Enhancement Proposals (PEPs) where relevant

## Commands

```bash
# Setup
source .venv/bin/activate
pip install -r requirements.txt

# Tests
python -m pytest tests/test_schema_guard.py -v   # schema guard first
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

## Test Schema Isolation (Mandatory)

- All tests MUST run only against test schemas, never production schemas.
- Required test schemas: `test_public`, `test_langgraph`, `test_audit`, `test_simpleme`.
- Any SQL using `public`, `langgraph`, `audit`, or `simpleme` must be rewritten to the corresponding `test_*` schema during test execution.
- Test scripts must live under `tests/` (for manual scripts, place them under `tests/manual/`).

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

### Specific Architectural Guidance

- **Modularity**: Create well-isolated components with clear interfaces
- **Extensibility**: Design with plugin/module capability in mind where appropriate
- **API Consistency**: Maintain uniform patterns across endpoint handlers
- **Logging**: Structure logs for monitoring, debugging and observability
- **Security**: Validate inputs, manage authentication/authorization appropriately
- **Performance**: Profile during development to identify bottlenecks early

## Code Style

- Line length: 88–100 characters
- Docstrings: Google-style or NumPy format
- Imports: stdlib → third-party → local, blank lines between groups
- Use specific exception types; raise on missing env vars (no defaults)
- Async only where genuine parallelism benefit exists

### Imports Order

1. Standard library imports
2. Third-party imports
3. Local application/library specific imports

Use blank lines to separate these groups.

### Error Handling

- Use specific exception types rather than bare `except:` clauses
- Provide meaningful exceptions with helpful error messages
- Implement consistent error logging and reporting patterns
- Distinguish between user-caused errors and system errors

### Async/Await

- Use async with caution; apply only when genuine parallelism benefits exist
- Manage async context properly with appropriate error handling
- Consider alternatives to async if complexity outweighs performance gains

### Testing Style

- Unit tests should be fast, focused on specific method/class behavior
- Integration tests to verify interaction between modules/components
- Use pytest fixtures for reusable test data/resources
- Apply AAA (Arrange, Act, Assert) pattern in test functions
- Maintain clear distinction between test methods (avoid shared mutable state)

## Environment Variables

All required; no defaults — missing vars must raise at startup. See `.env.example` for the full list (PostgreSQL, Qdrant, pool sizing, agent limits).

- Load environment variables using proper configuration management tools
- When loading environment variables, DO NOT provide default values
- If environment variables are missing, raise/throw appropriate exceptions
- Ensure environment validation at application startup to prevent runtime issues

## i18n

Default locale is `zh-HK` (香港繁體中文).

**All human-readable strings must be wrapped with `_()`** — this includes every `logger.*()` call, every `raise SomeError(...)` message, and every `print()` statement. No bare string literals in log/error output.

```python
# correct
from i18n import _
logger.info(_("Task %s completed"), task_id)
raise RuntimeError(_("Pool not initialised"))

# wrong — never do this
logger.info("Task %s completed", task_id)
raise RuntimeError("Pool not initialised")
```

Store translations in `locale/<lang>/LC_MESSAGES/agent_server.po`. Compile with `msgfmt` before deployment.

## Commit Messages

Imperative tone: `Add feature`, `Fix bug`, `Refactor component`. Tag breaking changes as `BREAKING:` with migration notes.

- Each PR should address one issue; include tests for functionality
- Address review feedback promptly; ensure changes pass all checks before merge
- Update relevant docs alongside code changes

## Configuration and Deployment

- **Settings**: Use environment variables or configuration files with sensible defaults and override support
- **Environment separation**: Support development/staging/production configurations
- **Dependency specification**: Pin versions in deployment but allow flexibility in development where feasible
- Keep dependencies minimal and justified; regularly audit for security updates
