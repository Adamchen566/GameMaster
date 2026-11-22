"""The ways of reaching a model: DeepSeek over HTTPS, Claude Code on this computer."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest

from app.agents.claude_code_model import ClaudeCodeModel
from app.agents.codex_model import DISABLED_FEATURES, CodexModel
from app.agents.contract import DECISION_SCHEMA
from app.agents.deepseek_model import DeepSeekModel
from app.agents.drivers import DRIVER_IDS, build_drivers, default_driver, narrator_driver
from app.agents.json_reply import parse_json_object, schema_instructions
from app.agents.model import ModelBadOutput, ModelRefused, ModelTimeout, ModelUnavailable
from app.config import Settings

ANSWER = {"action": "vote_team", "approve": True}


def ask(model: Any) -> Any:
    return model.complete(
        system="You play Avalon.",
        user='{"phase": "team_vote"}',
        schema=DECISION_SCHEMA,
        timeout_seconds=5,
    )


# --- reading an answer that no schema enforced ----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"action": "vote_team", "approve": true}',
        '```json\n{"action": "vote_team", "approve": true}\n```',
        'Here is my move: {"action": "vote_team", "approve": true} Good luck.',
    ],
)
def test_the_json_object_is_found_whatever_surrounds_it(text: str) -> None:
    assert parse_json_object(text) == ANSWER


@pytest.mark.parametrize("text", ["", "I approve.", "{not json}", "[1, 2]"])
def test_an_answer_without_a_json_object_is_bad_output(text: str) -> None:
    with pytest.raises(ModelBadOutput):
        parse_json_object(text)


def test_the_instructions_name_every_field() -> None:
    text = schema_instructions(DECISION_SCHEMA)

    for field in DECISION_SCHEMA["properties"]:
        assert f'"{field}"' in text


# --- DeepSeek ------------------------------------------------------------------------


def deepseek(handler: Any) -> DeepSeekModel:
    return DeepSeekModel("test-key", client=httpx.Client(transport=httpx.MockTransport(handler)))


def completion(text: str, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 812, "completion_tokens": 40},
    }


def test_deepseek_sends_one_json_mode_request_and_reads_the_answer() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=completion(json.dumps(ANSWER)))

    reply = ask(deepseek(handler))

    assert reply.data == ANSWER
    assert (reply.input_tokens, reply.output_tokens) == (812, 40)
    [request] = seen
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "deepseek-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    # JSON mode needs the fields spelled out: nothing else tells the model the shape.
    assert '"suspects"' in body["messages"][0]["content"]
    assert body["messages"][1]["content"] == '{"phase": "team_vote"}'


@pytest.mark.parametrize("status", [401, 402, 429, 500, 503])
def test_deepseek_http_errors_are_unavailable(status: int) -> None:
    model = deepseek(lambda request: httpx.Response(status, json={"error": {"message": "no"}}))

    with pytest.raises(ModelUnavailable, match=str(status)):
        ask(model)


def test_deepseek_timeout_and_connection_failure() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ModelTimeout):
        ask(deepseek(slow))
    with pytest.raises(ModelUnavailable):
        ask(deepseek(down))


def test_deepseek_cut_off_filtered_and_empty_answers() -> None:
    def answering(text: str, reason: str) -> DeepSeekModel:
        return deepseek(lambda request: httpx.Response(200, json=completion(text, reason)))

    with pytest.raises(ModelBadOutput, match="cut off"):
        ask(answering('{"action": "vote', "length"))
    with pytest.raises(ModelRefused):
        ask(answering("", "content_filter"))
    with pytest.raises(ModelBadOutput):
        ask(answering("   ", "stop"))
    with pytest.raises(ModelBadOutput):
        ask(deepseek(lambda request: httpx.Response(200, json={"unexpected": True})))


def test_deepseek_never_puts_the_key_in_an_error() -> None:
    model = deepseek(lambda request: httpx.Response(401, text="bad key test-key"))

    with pytest.raises(ModelUnavailable) as raised:
        ask(model)
    assert "test-key" not in str(raised.value)


# --- Claude Code on this computer -----------------------------------------------------


class FakeClaude:
    """Stands in for the command line: records how it was run, prints what it is told to."""

    def __init__(self, output: str = "", code: int = 0, fail: Exception | None = None) -> None:
        self.output, self.code, self.fail = output, code, fail
        self.runs: list[tuple[list[str], str, float]] = []

    def __call__(self, arguments: Sequence[str], stdin: str, timeout: float) -> tuple[int, str]:
        self.runs.append((list(arguments), stdin, timeout))
        if self.fail is not None:
            raise self.fail
        return self.code, self.output


def result(text: str, **extra: Any) -> str:
    return json.dumps(
        {
            "type": "result",
            "is_error": False,
            "result": text,
            "usage": {"input_tokens": 9, "output_tokens": 4},
        }
        | extra
    )


def test_claude_code_runs_without_tools_and_sends_the_prompt_on_stdin() -> None:
    run = FakeClaude(result(json.dumps(ANSWER)))

    reply = ask(ClaudeCodeModel("claude", run=run))

    assert reply.data == ANSWER
    assert (reply.input_tokens, reply.output_tokens) == (9, 4)
    [(arguments, stdin, timeout)] = run.runs
    assert arguments[:2] == ["claude", "-p"]
    # No tools: what the model reads includes text typed by other players.
    assert arguments[arguments.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in arguments
    assert "--no-session-persistence" in arguments
    assert "--dangerously-skip-permissions" not in arguments
    # Nothing from the game is ever on the command line.
    assert all("team_vote" not in argument and "Avalon" not in argument for argument in arguments)
    assert "You play Avalon." in stdin and '{"phase": "team_vote"}' in stdin
    assert timeout == 5


def test_claude_code_accepts_a_structured_answer_or_text_around_the_json() -> None:
    structured = FakeClaude(result("done", structured_output=ANSWER))
    wrapped = FakeClaude(
        "warning: something\n" + result(f"Sure:\n```json\n{json.dumps(ANSWER)}\n```")
    )

    assert ask(ClaudeCodeModel("claude", run=structured)).data == ANSWER
    assert ask(ClaudeCodeModel("claude", run=wrapped)).data == ANSWER


def test_claude_code_failures() -> None:
    def model(run: FakeClaude) -> ClaudeCodeModel:
        return ClaudeCodeModel("claude", run=run)

    with pytest.raises(ModelTimeout):
        ask(model(FakeClaude(fail=TimeoutError("120s"))))
    with pytest.raises(ModelUnavailable):
        ask(model(FakeClaude(fail=FileNotFoundError("claude"))))
    with pytest.raises(ModelUnavailable):
        ask(model(FakeClaude("not logged in", code=1)))
    with pytest.raises(ModelUnavailable):
        ask(model(FakeClaude(json.dumps({"is_error": True, "result": "limit reached"}))))
    with pytest.raises(ModelBadOutput):
        ask(model(FakeClaude(result("I would rather not say."))))


def test_claude_code_reports_whether_it_is_logged_in_and_asks_only_once() -> None:
    logged_in = FakeClaude("Logged in", code=0)
    logged_out = FakeClaude("Not logged in", code=1)
    signed_in, signed_out = (
        ClaudeCodeModel("claude", run=logged_in),
        ClaudeCodeModel("claude", run=logged_out),
    )

    assert signed_in.problem() is None
    assert signed_in.problem() is None
    assert signed_out.problem() == "not_logged_in"
    assert len(logged_in.runs) == 1
    assert logged_in.runs[0][0] == ["claude", "auth", "status"]


# --- which drivers a server offers ---------------------------------------------------


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **{"llm_drivers": "auto", **values})  # type: ignore[call-arg]


def test_nothing_is_offered_until_something_is_set_up() -> None:
    drivers = build_drivers(settings(), find_claude_code=lambda: None, find_codex=lambda: None)

    assert tuple(drivers) == DRIVER_IDS
    assert {name: driver.problem for name, driver in drivers.items()} == {
        "claude": "missing_anthropic_api_key",
        "deepseek": "missing_deepseek_api_key",
        "claude_code": "claude_code_not_installed",
        "codex": "codex_not_installed",
    }
    assert default_driver(drivers) is None
    assert narrator_driver(drivers) is None


def test_a_key_or_an_installed_client_turns_its_driver_on() -> None:
    drivers = build_drivers(
        settings(deepseek_api_key="k"),
        find_claude_code=lambda: "C:/bin/claude.exe",
        find_codex=lambda: "C:/bin/codex.exe",
    )

    assert [name for name, driver in drivers.items() if driver.available] == [
        "deepseek",
        "claude_code",
        "codex",
    ]
    chosen = default_driver(drivers)
    assert chosen is not None and chosen.id == "deepseek"
    # The local client is too slow to voice the game master.
    voice = narrator_driver(drivers)
    assert voice is not None and voice.id == "deepseek"
    assert drivers["claude_code"].timeout_seconds == 120.0


def test_only_a_local_client_means_seats_but_no_ai_game_master() -> None:
    drivers = build_drivers(settings(), find_claude_code=lambda: "claude", find_codex=lambda: None)

    chosen = default_driver(drivers)
    assert chosen is not None and chosen.id == "claude_code"
    assert narrator_driver(drivers) is None


def test_drivers_can_be_limited_or_switched_off() -> None:
    everything = {"anthropic_api_key": "a", "deepseek_api_key": "d"}

    def build(drivers: str) -> dict[str, Any]:
        return build_drivers(
            settings(llm_drivers=drivers, **everything),
            find_claude_code=lambda: "claude",
            find_codex=lambda: "codex",
        )

    none, one = build("none"), build("deepseek")

    assert not any(driver.available for driver in none.values())
    assert {driver.problem for driver in none.values()} == {"switched_off"}
    assert [name for name, driver in one.items() if driver.available] == ["deepseek"]


# --- Codex on this computer -----------------------------------------------------------


class FakeCodex:
    """Stands in for `codex exec`: writes its answer to the file it is told to, like Codex does."""

    def __init__(
        self,
        answer: str | None = "",
        output: str = "",
        code: int = 0,
        fail: Exception | None = None,
    ) -> None:
        self.answer, self.output, self.code, self.fail = answer, output, code, fail
        self.runs: list[tuple[list[str], str, float]] = []
        self.schema: dict[str, Any] | None = None

    def __call__(self, arguments: Sequence[str], stdin: str, timeout: float) -> tuple[int, str]:
        self.runs.append((list(arguments), stdin, timeout))
        if self.fail is not None:
            raise self.fail
        if "--output-schema" in arguments:
            path = arguments[list(arguments).index("--output-schema") + 1]
            with open(path, encoding="utf-8") as file:
                self.schema = json.load(file)
        if self.answer is not None and "--output-last-message" in arguments:
            path = arguments[list(arguments).index("--output-last-message") + 1]
            with open(path, "w", encoding="utf-8") as file:
                file.write(self.answer)
        return self.code, self.output


def test_codex_runs_without_tools_in_a_read_only_sandbox_and_reads_its_answer_file() -> None:
    run = FakeCodex(json.dumps(ANSWER), output="codex\n{...}\ntokens used\n14,537\n")

    reply = ask(CodexModel("codex", run=run))

    assert reply.data == ANSWER
    assert reply.output_tokens == 14537
    [(arguments, stdin, timeout)] = run.runs
    assert arguments[:2] == ["codex", "exec"]
    assert arguments[-1] == "-", "the prompt comes from standard input"
    assert arguments[arguments.index("--sandbox") + 1] == "read-only"
    for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check"):
        assert flag in arguments
    disabled = {arguments[i + 1] for i, value in enumerate(arguments) if value == "--disable"}
    assert disabled == set(DISABLED_FEATURES) and "shell_tool" in disabled
    assert "--dangerously-bypass-approvals-and-sandbox" not in arguments
    assert all("team_vote" not in argument and "Avalon" not in argument for argument in arguments)
    assert "You play Avalon." in stdin and '{"phase": "team_vote"}' in stdin
    # The answer is held to the same schema the Claude API uses.
    assert run.schema == DECISION_SCHEMA
    assert timeout == 5


def test_codex_failures() -> None:
    def model(run: FakeCodex) -> CodexModel:
        return CodexModel("codex", run=run)

    with pytest.raises(ModelTimeout):
        ask(model(FakeCodex(fail=TimeoutError("120s"))))
    with pytest.raises(ModelUnavailable):
        ask(model(FakeCodex(fail=FileNotFoundError("codex"))))
    with pytest.raises(ModelUnavailable, match="usage limit"):
        ask(model(FakeCodex(None, output="error: usage limit reached", code=1)))
    with pytest.raises(ModelBadOutput):
        ask(model(FakeCodex("I approve.")))


def test_codex_reports_whether_it_is_logged_in() -> None:
    logged_in = FakeCodex(None, output="Logged in using ChatGPT")
    logged_out = FakeCodex(None, output="Not logged in", code=1)

    assert CodexModel("codex", run=logged_in).problem() is None
    assert CodexModel("codex", run=logged_out).problem() == "codex_not_logged_in"
    assert logged_in.runs[0][0] == ["codex", "login", "status"]


def test_codex_is_found_where_the_desktop_app_installs_it(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from app.agents import codex_model

    older = tmp_path / "OpenAI" / "Codex" / "bin" / "a" / "codex.exe"
    newer = tmp_path / "OpenAI" / "Codex" / "bin" / "b" / "codex.exe"
    for path, when in ((older, 1_000), (newer, 2_000)):
        path.parent.mkdir(parents=True)
        path.write_text("")
        os.utime(path, (when, when))
    monkeypatch.setattr(codex_model.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert codex_model.find_codex() == str(newer)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nowhere"))
    assert codex_model.find_codex() is None
