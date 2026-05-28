import logging

import logger_setup


def _reset_root_handlers():
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.WARNING)


def test_httpx_request_logs_are_debug_only(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(logger_setup, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(logger_setup, "_LOG_FILE", tmp_path / "console.log")
    _reset_root_handlers()

    try:
        logger_setup.setup_logging(logging.INFO)
        capsys.readouterr()

        logging.getLogger("httpx").info("HTTP Request: GET https://example.test")

        captured = capsys.readouterr()
        assert "HTTP Request:" not in captured.err
        assert "HTTP Request:" not in (tmp_path / "console.log").read_text()
    finally:
        _reset_root_handlers()

    monkeypatch.setattr(logger_setup, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(logger_setup, "_LOG_FILE", tmp_path / "debug.log")
    logger_setup.setup_logging(logging.DEBUG)
    capsys.readouterr()

    try:
        logging.getLogger("httpx").info("HTTP Request: GET https://example.test")

        captured = capsys.readouterr()
        assert "[DEBUG]" in captured.err
        assert "HTTP Request:" in captured.err
    finally:
        _reset_root_handlers()
