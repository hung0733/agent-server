import json
import re
from typing import List, Dict, Any, Optional


class LLMClient:
    """OpenAI-compatible LLM client for chat completion using httpx."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict] = None,
    ) -> str:
        client = self._get_client()

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if response_format:
            payload["response_format"] = response_format

        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        return data["choices"][0]["message"]["content"]

    def extract_json(self, text: str) -> Any:
        if not text:
            return None

        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        json_block_pattern = r"```json\s*([\s\S]*?)\s*```"
        matches = re.findall(json_block_pattern, text, re.IGNORECASE)
        if matches:
            try:
                return json.loads(matches[0].strip())
            except json.JSONDecodeError:
                pass

        generic_block_pattern = r"```\s*([\s\S]*?)\s*```"
        matches = re.findall(generic_block_pattern, text)
        if matches:
            for match in matches:
                try:
                    return json.loads(match.strip())
                except json.JSONDecodeError:
                    continue

        start_obj = text.find("{")
        start_arr = text.find("[")

        if start_obj == -1 and start_arr == -1:
            return None

        if start_arr == -1 or (start_obj != -1 and start_obj < start_arr):
            json_str = self._extract_balanced_braces(text[start_obj:], "{", "}")
        else:
            json_str = self._extract_balanced_braces(text[start_arr:], "[", "]")

        if json_str:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        cleaned = self._clean_json_string(text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        return None

    def _extract_balanced_braces(self, text: str, open_char: str, close_char: str) -> Optional[str]:
        if not text or text[0] != open_char:
            return None

        count = 0
        in_string = False
        escape_next = False

        for i, char in enumerate(text):
            if escape_next:
                escape_next = False
                continue

            if char == "\\":
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == open_char:
                count += 1
            elif char == close_char:
                count -= 1
                if count == 0:
                    return text[: i + 1]

        return None

    def _clean_json_string(self, text: str) -> str:
        prefixes = [
            "Here's the JSON:",
            "Here is the JSON:",
            "JSON output:",
            "Output:",
            "Result:",
        ]
        cleaned = text.strip()
        for prefix in prefixes:
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix):].strip()

        cleaned = re.sub(r",\s*([\}\]])", r"\1", cleaned)

        cleaned = re.sub(r"//.*$", "", cleaned, flags=re.MULTILINE)

        return cleaned
