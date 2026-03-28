"""Shared test-schema configuration and SQL schema rewriting helpers."""

from __future__ import annotations

import re

TEST_PUBLIC_SCHEMA = "test_public"
TEST_LANGGRAPH_SCHEMA = "test_langgraph"
TEST_AUDIT_SCHEMA = "test_audit"
TEST_SIMPLEME_SCHEMA = "test_simpleme"

SOURCE_TO_TEST_SCHEMA = {
    "public": TEST_PUBLIC_SCHEMA,
    "langgraph": TEST_LANGGRAPH_SCHEMA,
    "audit": TEST_AUDIT_SCHEMA,
    "simpleme": TEST_SIMPLEME_SCHEMA,
}

_SCHEMA_PREFIX_RE = re.compile(r"\b(public|langgraph|audit|simpleme)\.", re.IGNORECASE)


def rewrite_sql_schemas(sql: str) -> str:
    """Rewrite production schema prefixes to test schema prefixes."""
    if not sql:
        return sql

    def _replace(match: re.Match[str]) -> str:
        source_schema = match.group(1).lower()
        return f"{SOURCE_TO_TEST_SCHEMA[source_schema]}."

    return _SCHEMA_PREFIX_RE.sub(_replace, sql)
