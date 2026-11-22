"""`ModelClient` backed by the DeepSeek API (`POST /chat/completions`).

DeepSeek has no official Python SDK; the endpoint is plain HTTPS, called here
with `httpx`. JSON mode makes the reply a JSON object but does not hold it to a
schema, so the fields are spelled out in the system prompt and the answer is
checked by the contract like any other. Thinking is switched off: a game turn
has a fixed time allowance.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.agents.json_reply import parse_json_object, schema_instructions
from app.agents.model import (
    ModelBadOutput,
    ModelRefused,
    ModelReply,
    ModelTimeout,
    ModelUnavailable,
)

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"


class DeepSeekModel:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        max_tokens: int = 1200,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._max_tokens = max_tokens
        self._client = client if client is not None else httpx.Client()

    def complete(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        timeout_seconds: float,
    ) -> ModelReply:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": f"{system}\n\n{schema_instructions(schema)}"},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "max_tokens": self._max_tokens,
            "stream": False,
        }
        try:
            response = self._client.post(
                self._url,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise ModelTimeout(str(error)) from error
        except httpx.HTTPError as error:
            raise ModelUnavailable(f"connection failed: {type(error).__name__}") from error

        if response.status_code != 200:
            # 401 bad key, 402 no balance, 429 rate limit, 5xx server trouble.
            raise ModelUnavailable(f"API error {response.status_code}")
        try:
            payload = response.json()
            choice = payload["choices"][0]
            text = choice["message"]["content"]
            usage = payload.get("usage") or {}
        except (ValueError, LookupError, TypeError) as error:
            raise ModelBadOutput("The response was not a chat completion.") from error

        reason = choice.get("finish_reason")
        if reason == "content_filter":
            raise ModelRefused("the model declined to answer")
        if reason == "length":
            raise ModelBadOutput("The answer was cut off before it was complete.")
        if not isinstance(text, str) or not text.strip():
            raise ModelBadOutput("The answer contained no text.")

        return ModelReply(
            data=parse_json_object(text),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )
