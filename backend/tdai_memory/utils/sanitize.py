from __future__ import annotations

import re
from html import escape as _html_escape

_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore (all )?(previous|above|prior) (instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"disregard (all )?(previous|above|prior) (instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"forget (all )?(previous|above|prior) (instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"override (all )?(previous|above|prior|system) (instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"you are now", re.IGNORECASE),
    re.compile(r"new (system )?prompt", re.IGNORECASE),
    re.compile(r"from now on you (are|must|will|should)", re.IGNORECASE),
    re.compile(r"your (new|real|true|actual) (name|identity|role|purpose) is", re.IGNORECASE),
    re.compile(r"you (are|must) (to )?act as", re.IGNORECASE),
    re.compile(r"do not (follow|obey|listen to)", re.IGNORECASE),
    re.compile(r"(disobey|ignore|override|bypass) (system|safety|content) (prompt|policy|filter|rule)", re.IGNORECASE),
    re.compile(r"\[system\]", re.IGNORECASE),
    re.compile(r"\[/system\]", re.IGNORECASE),
    re.compile(r"<\|system\|>", re.IGNORECASE),
    re.compile(r"</\|system\|>", re.IGNORECASE),
    re.compile(r"DAN\b", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"role[\s]*:[\s]*system", re.IGNORECASE),
    re.compile(r"system\s*:\s*You are", re.IGNORECASE),
]

_GATEWAY_TAGS_RE = re.compile(
    r"<\|gateway_metadata\|>.*?</\|gateway_metadata\|>|<\|gateway_context\|>.*?</\|gateway_context\|>|<\|image_base64\|>.*?</\|image_base64\|>",
    re.DOTALL,
)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.DOTALL)
_BASE64_RE = re.compile(r"data:image\/[^;]+;base64,[A-Za-z0-9+/=]+")
_RELEVANT_MEMORIES_RE = re.compile(r"<relevant-memories>.*?</relevant-memories>\s*", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_text(text: str) -> str:
    text = _GATEWAY_TAGS_RE.sub("", text)
    text = _BASE64_RE.sub("[image]", text)
    text = _RELEVANT_MEMORIES_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def should_capture_l0(text: str) -> bool:
    if not text or not text.strip():
        return False
    if len(text.strip()) < 2:
        return False
    if len(text) > 50000:
        return False
    return True


def should_extract_l1(messages: list[dict]) -> bool:
    if not messages:
        return False
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if not user_msgs:
        return False
    total_chars = sum(len(m.get("content", "")) for m in user_msgs)
    return total_chars >= 10


def looks_like_prompt_injection(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(text_lower):
            return True
    return False


def sanitize_json_for_parse(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = text.replace("\t", " ").replace("\r", "")
    return text


def escape_xml_tags(text: str) -> str:
    return _html_escape(text, quote=False)


def strip_code_blocks(text: str) -> str:
    return _CODE_BLOCK_RE.sub("[code block]", text)


def sanitize_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def strip_html(text: str) -> str:
    return sanitize_html(text)
