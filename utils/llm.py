"""DeepSeek API client via Anthropic Messages protocol."""

import json
import logging
import os
import time

import requests as req

logger = logging.getLogger("llm")

ANTHROPIC_VERSION = "2023-06-01"


class LLMError(Exception):
    """LLM API error."""


class LLMClient:
    """Client for DeepSeek API via Anthropic Messages format."""

    def __init__(self, config: dict):
        self.api_base = config["api_base"].rstrip("/")
        self.api_key = os.environ.get(config["api_key_env"])
        if not self.api_key:
            raise LLMError(f"Env var {config['api_key_env']} not set")
        self.model = config["model"]
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.3)
        self.max_retries = config.get("max_retries", 2)
        self.timeout = config.get("timeout_seconds", 120)
        self._warned = False

    def messages_create(self, system: str, messages: list[dict]) -> str:
        """Call Anthropic Messages API. Returns text content."""
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": messages,
        }

        last_error = None
        for attempt in range(1 + self.max_retries):
            try:
                resp = req.post(
                    f"{self.api_base}/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": ANTHROPIC_VERSION,
                        "content-type": "application/json",
                    },
                    json=body,
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    blocks = data.get("content", [])
                    texts = [b["text"] for b in blocks if b.get("type") == "text"]
                    return "\n".join(texts)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("retry-after", 5))
                    logger.warning(
                        "LLM rate limited (429), retrying in %ds (attempt %d/%d)",
                        retry_after,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(retry_after)
                    continue

                if resp.status_code == 401:
                    msg = f"LLM auth failed (401): {resp.text[:300]}"
                    raise LLMError(msg)

                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if attempt < self.max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "LLM attempt %d failed: %s. retry in %ds",
                        attempt + 1,
                        last_error,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                raise LLMError(last_error)

            except req.Timeout:
                last_error = "Request timeout"
                if attempt < self.max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "LLM timeout, retry in %ds (attempt %d/%d)",
                        wait,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(wait)
                    continue
                raise LLMError("All retries failed: timeout")
            except req.ConnectionError as e:
                last_error = f"Connection error: {e}"
                if attempt < self.max_retries:
                    wait = 2**attempt
                    time.sleep(wait)
                    continue
                raise LLMError(last_error)

        raise LLMError(f"All retries failed: {last_error}")

    def extract_json(self, text: str) -> dict | None:
        """Try to extract JSON from LLM response, handling markdown fences."""
        # Try direct parse first
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from ```json ... ``` block
        import re

        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding outermost { ... }
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        return None
