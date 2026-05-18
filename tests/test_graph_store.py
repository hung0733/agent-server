from urllib.parse import parse_qs, unquote, urlparse

from backend.graph.graph_store import GraphStore


def test_langgraph_dsn_can_use_test_schema(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "password")
    monkeypatch.setenv("POSTGRES_DB", "agent")
    monkeypatch.setenv("LANGGRAPH_SCHEMA", "langgraph")
    monkeypatch.setenv("TEST_LANGGRAPH_SCHEMA", "test_langgraph")

    dsn = GraphStore._build_langgraph_dsn(use_test_schema=True)
    options = parse_qs(urlparse(dsn).query)["options"][0]

    assert unquote(options) == "-c search_path=test_langgraph,public"
    assert GraphStore._get_langgraph_schema(use_test_schema=True) == "test_langgraph"
