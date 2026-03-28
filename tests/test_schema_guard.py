"""Safety guard tests enforcing test schema isolation."""

from __future__ import annotations

import re

from tests.schema_config import (
    TEST_AUDIT_SCHEMA,
    TEST_LANGGRAPH_SCHEMA,
    TEST_PUBLIC_SCHEMA,
    TEST_SIMPLEME_SCHEMA,
    rewrite_sql_schemas,
)


def test_schema_names_use_test_prefix() -> None:
    assert TEST_PUBLIC_SCHEMA.startswith("test_")
    assert TEST_LANGGRAPH_SCHEMA.startswith("test_")
    assert TEST_AUDIT_SCHEMA.startswith("test_")
    assert TEST_SIMPLEME_SCHEMA.startswith("test_")


def test_sql_schema_rewrite_covers_all_required_schemas() -> None:
    source_sql = (
        "SELECT * FROM public.users u "
        "JOIN langgraph.checkpoints c ON 1=1 "
        "JOIN audit.audit_log a ON 1=1 "
        "JOIN simpleme.dialogues d ON 1=1"
    )
    rewritten = rewrite_sql_schemas(source_sql)

    assert re.search(r"\bpublic\.", rewritten) is None
    assert re.search(r"\blanggraph\.", rewritten) is None
    assert re.search(r"\baudit\.", rewritten) is None
    assert re.search(r"\bsimpleme\.", rewritten) is None

    assert f"{TEST_PUBLIC_SCHEMA}.users" in rewritten
    assert f"{TEST_LANGGRAPH_SCHEMA}.checkpoints" in rewritten
    assert f"{TEST_AUDIT_SCHEMA}.audit_log" in rewritten
    assert f"{TEST_SIMPLEME_SCHEMA}.dialogues" in rewritten
