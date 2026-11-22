"""`ModelClient` backed by the Claude API (official `anthropic` SDK).

Structured outputs make the reply one JSON object matching the schema. The SDK's
own retries are switched off: a game turn has a fixed time allowance, and the
caller decides what happens when it runs out.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

import anthropic
from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam

from app.agents.model import (
    ModelBadOutput,
    ModelRefused,
    ModelReply,
    ModelTimeout,
    ModelUnavailable,
)

DEFAULT_MODEL = "claude-opus-5-5"
# If the model declines on policy grounds, the API re-runs the request on a
# fallback model inside the same call instead of returning a refusal.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class AnthropicModel:
    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        *,
        model: str = DEFAULT_MODEL,
        effort: Effort = "low",
        max_tokens: int = 4000,
    ) -> None:
        # The zero-argument client reads credentials from the environment
        # (ANTHROPIC_API_KEY or an `ant auth login` profile).
        self._client = client if client is not None else anthropic.Anthropic()
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens

    def complete(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        timeout_seconds: float,
    ) -> ModelReply:
        messages: list[BetaMessageParam] = [{"role": "user", "content": user}]
        output_config: BetaOutputConfigParam = {
            "effort": self._effort,
            "format": {"type": "json_schema", "schema": dict(schema)},
        }
        try:
            response = self._client.with_options(
                timeout=timeout_seconds, max_retries=0
            ).beta.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,
                output_config=output_config,
                betas=[_FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APITimeoutError as error:
            # Must come first: a timeout is also an APIConnectionError.
            raise ModelTimeout(str(error)) from error
        except anthropic.APIConnectionError as error:
            raise ModelUnavailable(f"connection failed: {error}") from error
        except anthropic.RateLimitError as error:
            raise ModelUnavailable("rate limited") from error
        except anthropic.APIStatusError as error:
            raise ModelUnavailable(f"API error {error.status_code}") from error

        if response.stop_reason == "refusal":
            raise ModelRefused("the model declined to answer")
        if response.stop_reason == "max_tokens":
            raise ModelBadOutput("The answer was cut off before it was complete.")

        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise ModelBadOutput("The answer contained no text.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ModelBadOutput("The answer was not valid JSON.") from error
        if not isinstance(data, dict):
            raise ModelBadOutput("The answer must be a JSON object.")

        return ModelReply(
            data=data,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
