#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Web Search Tool Implementation.

使用 DuckDuckGo 或其他搜索引擎進行網絡搜索。
"""
import logging
from typing import Any, Dict

from i18n import _

logger = logging.getLogger(__name__)


async def execute_web_search(
    query: str,
    num_results: int = 5,
    _config: Dict[str, Any] | None = None,
) -> str:
    """執行網絡搜索並返回結果。

    Args:
        query: 搜索查詢字符串
        num_results: 要返回的結果數量（預設: 5，最大: 10）
        _config: 工具配置（由 tools.tools._make_executor 自動注入）

    Returns:
        格式化的搜索結果字符串

    Example:
        >>> result = await execute_web_search("Python async programming", num_results=3)
        >>> print(result)
    """
    _config = _config or {}
    search_engine = _config.get("search_engine", "duckduckgo")
    timeout = _config.get("timeout", 10)
    safe_search = _config.get("safe_search", True)

    logger.info(
        _("🔍 執行網絡搜索: query='%s', num_results=%d, engine=%s"),
        query,
        num_results,
        search_engine,
    )

    # 限制結果數量
    num_results = min(max(1, num_results), 10)

    try:
        # 使用 duckduckgo-search 庫
        if search_engine == "duckduckgo":
            return await _search_with_duckduckgo(
                query, num_results, safe_search, timeout
            )
        else:
            logger.warning(
                _("⚠️ 不支援的搜索引擎: %s，使用 DuckDuckGo 替代"), search_engine
            )
            return await _search_with_duckduckgo(
                query, num_results, safe_search, timeout
            )

    except Exception as exc:
        logger.error(_("❌ 網絡搜索失敗: %s"), exc, exc_info=True)
        return _("搜索失敗：%s") % str(exc)


async def _search_with_duckduckgo(
    query: str, num_results: int, safe_search: bool, timeout: int
) -> str:
    """使用 DuckDuckGo 進行搜索。

    Args:
        query: 搜索查詢
        num_results: 結果數量
        safe_search: 是否啟用安全搜索
        timeout: 超時時間（秒）

    Returns:
        格式化的搜索結果
    """
    try:
        # 嘗試導入 duckduckgo_search
        from duckduckgo_search import DDGS
    except ImportError:
        logger.error(
            _(
                "❌ 缺少依賴：duckduckgo-search。請執行：pip install duckduckgo-search"
            )
        )
        return _(
            "錯誤：缺少 duckduckgo-search 庫。請聯繫管理員安裝依賴。\n"
            "安裝命令：pip install duckduckgo-search"
        )

    try:
        # 執行搜索
        ddgs = DDGS(timeout=timeout)
        results = list(
            ddgs.text(
                query,
                max_results=num_results,
                safesearch="on" if safe_search else "off",
            )
        )

        if not results:
            return _("沒有找到相關結果：%s") % query

        # 格式化結果
        formatted_results = [_("🔍 搜索結果：%s\n") % query]

        for idx, result in enumerate(results, 1):
            title = result.get("title", _("無標題"))
            snippet = result.get("body", _("無描述"))
            url = result.get("href", _("無連結"))

            formatted_results.append(
                f"\n{idx}. **{title}**\n"
                f"   {snippet}\n"
                f"   🔗 {url}\n"
            )

        logger.info(_("✅ 搜索成功，返回 %d 個結果"), len(results))
        return "".join(formatted_results)

    except Exception as exc:
        logger.error(_("❌ DuckDuckGo 搜索失敗: %s"), exc, exc_info=True)
        return _("搜索失敗：%s") % str(exc)


async def execute_web_fetch(
    url: str,
    max_length: int = 5000,
    _config: Dict[str, Any] | None = None,
) -> str:
    """抓取 URL 並提取可讀的文字內容。

    Args:
        url: 要抓取的 URL。
        max_length: 返回文字的最大字符數（預設: 5000）。
        _config: 工具配置（由 tools.tools._make_executor 自動注入）。

    Returns:
        提取的純文字內容，超過 max_length 時截斷。
    """
    _config = _config or {}
    timeout = _config.get("timeout", 15)

    logger.info(_("🌐 抓取網頁: url='%s'"), url)

    try:
        import urllib.request
        import urllib.error
        import html.parser

        class _TextExtractor(html.parser.HTMLParser):
            """Simple HTML → plain-text extractor."""

            _SKIP_TAGS = {"script", "style", "noscript", "head"}

            def __init__(self) -> None:
                super().__init__()
                self._skip_depth = 0
                self.parts: list[str] = []

            def handle_starttag(self, tag: str, attrs: list) -> None:
                if tag in self._SKIP_TAGS:
                    self._skip_depth += 1

            def handle_endtag(self, tag: str) -> None:
                if tag in self._SKIP_TAGS and self._skip_depth:
                    self._skip_depth -= 1

            def handle_data(self, data: str) -> None:
                if not self._skip_depth:
                    stripped = data.strip()
                    if stripped:
                        self.parts.append(stripped)

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AgentBot/1.0)"},
        )
        import socket
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read(512 * 1024)  # max 512 KB
                charset = resp.headers.get_content_charset() or "utf-8"
        finally:
            socket.setdefaulttimeout(old_timeout)

        html_text = raw.decode(charset, errors="replace")
        extractor = _TextExtractor()
        extractor.feed(html_text)
        text = "\n".join(extractor.parts)

        if len(text) > max_length:
            text = text[:max_length] + _("\n...(內容已截斷，共 %d 字符)") % len(text)

        logger.info(_("✅ 網頁抓取成功，返回 %d 字符"), len(text))
        return text or _("⚠️ 未提取到可讀內容: %s") % url

    except Exception as exc:
        logger.error(_("❌ 網頁抓取失敗: %s"), exc, exc_info=True)
        return _("抓取失敗：%s") % str(exc)
