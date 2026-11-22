"""The Claude adapter, against a stand-in for the SDK client.

No request leaves the machine. What is checked is the request this code
builds and how it maps the SDK's responses and errors; whether the live API
accepts the request can only be checked with a real key.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from app.agents.anthropic_model import AnthropicModel
from app.agents.model import ModelBadOutput, ModelRefused, ModelTimeout, ModelUnavailable

SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def message(text: str | None = '{"action": "vote_team"}', stop_reason: str = "end_turn") -> Any:
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        usage=SimpleNamespace(input_tokens=1234, output_tokens=56),
    )


class FakeClient:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome
        self.options: dict[str, Any] = {}
        self.request: dict[str, Any] = {}
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def with_options(self, **options: Any) -> FakeClient:
        self.options = options
        return self

    def _create(self, **request: Any) -> Any:
        self.request = request
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def ask(client: FakeClient, **settings: Any) -> Any:
    model = AnthropicModel(client, **settings)  # type: ignore[arg-type]
    return model.complete(system="SYSTEM", user="USER", schema=SCHEMA, timeout_seconds=8.0)


def status_error(cls: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    return cls("nope", response=httpx2.Response(status, request=REQUEST), body=None)


def test_reply_is_parsed_and_tokens_reported() -> None:
    reply = ask(FakeClient(message('{"action": "vote_team", "approve": true}')))

    assert reply.data == {"action": "vote_team", "approve": True}
    assert (reply.input_tokens, reply.output_tokens) == (1234, 56)


def test_request_uses_structured_output_a_time_limit_and_no_sdk_retries() -> None:
    client = FakeClient(message())

    ask(client)

    assert client.options == {"timeout": 8.0, "max_retries": 0}
    assert client.request == {
        "model": "claude-opus-5-5",
        "max_tokens": 4000,
        "system": "SYSTEM",
        "messages": [{"role": "user", "content": "USER"}],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }


def test_model_and_effort_can_be_configured() -> None:
    client = FakeClient(message())

    ask(client, model="claude-haiku-5-5", effort="medium", max_tokens=1000)

    assert client.request["model"] == "claude-haiku-5-5"
    assert client.request["output_config"]["effort"] == "medium"
    assert client.request["max_tokens"] == 1000


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (anthropic.APITimeoutError(request=REQUEST), ModelTimeout),
        (anthropic.APIConnectionError(request=REQUEST), ModelUnavailable),
        (status_error(anthropic.RateLimitError, 429), ModelUnavailable),
        (status_error(anthropic.AuthenticationError, 401), ModelUnavailable),
        (status_error(anthropic.BadRequestError, 400), ModelUnavailable),
        (status_error(anthropic.InternalServerError, 500), ModelUnavailable),
    ],
)
def test_sdk_errors_become_model_errors(failure: Exception, expected: type[Exception]) -> None:
    with pytest.raises(expected):
        ask(FakeClient(failure))


def test_refusal_is_reported_as_a_refusal() -> None:
    with pytest.raises(ModelRefused):
        ask(FakeClient(message(stop_reason="refusal")))


@pytest.mark.parametrize(
    "response",
    [
        message(stop_reason="max_tokens"),
        message(text=None),
        message(text="I think I will approve."),
        message(text='["vote_team"]'),
    ],
)
def test_unusable_answers_are_bad_output(response: Any) -> None:
    with pytest.raises(ModelBadOutput):
        ask(FakeClient(response))
