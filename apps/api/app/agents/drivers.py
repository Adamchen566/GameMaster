"""Who can play a model-driven seat on this server.

A driver is one way of reaching a model. Each seat picks its own, so one table
can mix them:

    claude       the Claude API                needs ANTHROPIC_API_KEY, paid per call
    deepseek     the DeepSeek API              needs DEEPSEEK_API_KEY, paid per call
    claude_code  Claude Code on this computer  needs a login, uses that subscription
    codex        Codex on this computer        needs a ChatGPT login, uses that subscription

A driver that cannot be used is still listed, with the reason, so the lobby can
say what is missing instead of hiding the choice.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.agents.model import ModelClient
from app.config import Settings

DRIVER_IDS = ("claude", "deepseek", "claude_code", "codex")
API_DRIVERS = ("claude", "deepseek")
"""Fast enough for the game master, who has a few seconds per line."""

LABELS = {
    "claude": "Claude",
    "deepseek": "DeepSeek",
    "claude_code": "Claude Code",
    "codex": "Codex",
}


@dataclass(frozen=True, slots=True)
class Driver:
    id: str
    label: str
    model: ModelClient | None
    """None when the driver cannot be used."""
    timeout_seconds: float
    problem: str | None = None
    """Why it cannot be used: a short code the client turns into a sentence."""
    check: Callable[[], str | None] | None = None
    """A slower check made when someone asks, e.g. whether a local client is logged in."""

    @property
    def available(self) -> bool:
        return self.model is not None

    def current_problem(self) -> str | None:
        if self.model is None:
            return self.problem
        return self.check() if self.check is not None else None


def _wanted(settings: Settings) -> set[str] | None:
    """The drivers to offer, or None for "whatever is set up"."""
    raw = settings.llm_drivers.strip().lower()
    if raw == "auto":
        return None
    return {part.strip() for part in raw.split(",") if part.strip() in DRIVER_IDS}


def build_drivers(
    settings: Settings,
    *,
    find_claude_code: Callable[[], str | None] | None = None,
    find_codex: Callable[[], str | None] | None = None,
) -> dict[str, Driver]:
    """Every known driver, usable or not, in the order the lobby shows them."""
    wanted = _wanted(settings)

    def off(driver_id: str, problem: str, timeout: float) -> Driver:
        return Driver(driver_id, LABELS[driver_id], None, timeout, problem)

    def enabled(driver_id: str) -> bool:
        return wanted is None or driver_id in wanted

    drivers: dict[str, Driver] = {}

    # Claude API. `LLM_PROVIDER=anthropic` is the older switch and still turns it on;
    # the SDK then finds the key itself.
    timeout = settings.llm_player_timeout_seconds
    has_key = bool(settings.anthropic_api_key) or settings.llm_provider == "anthropic"
    legacy = settings.llm_provider == "anthropic"
    if not (enabled("claude") or legacy):
        drivers["claude"] = off("claude", "switched_off", timeout)
    elif not has_key:
        drivers["claude"] = off("claude", "missing_anthropic_api_key", timeout)
    else:
        # Imported here so the SDK is only loaded when it is used.
        import anthropic

        from app.agents.anthropic_model import AnthropicModel

        client = (
            anthropic.Anthropic(api_key=settings.anthropic_api_key)
            if settings.anthropic_api_key
            else None
        )
        drivers["claude"] = Driver(
            "claude",
            LABELS["claude"],
            AnthropicModel(client, model=settings.llm_model, effort=settings.llm_effort),
            timeout,
        )

    timeout = settings.deepseek_timeout_seconds
    if not enabled("deepseek"):
        drivers["deepseek"] = off("deepseek", "switched_off", timeout)
    elif not settings.deepseek_api_key:
        drivers["deepseek"] = off("deepseek", "missing_deepseek_api_key", timeout)
    else:
        from app.agents.deepseek_model import DeepSeekModel

        drivers["deepseek"] = Driver(
            "deepseek",
            LABELS["deepseek"],
            DeepSeekModel(
                settings.deepseek_api_key,
                model=settings.deepseek_model,
                base_url=settings.deepseek_base_url,
            ),
            timeout,
        )

    timeout = settings.claude_code_timeout_seconds
    if not enabled("claude_code"):
        drivers["claude_code"] = off("claude_code", "switched_off", timeout)
    else:
        from app.agents.claude_code_model import ClaudeCodeModel, find_claude

        executable = (find_claude_code or find_claude)()
        if executable is None:
            drivers["claude_code"] = off("claude_code", "claude_code_not_installed", timeout)
        else:
            local = ClaudeCodeModel(executable, model=settings.claude_code_model)
            drivers["claude_code"] = Driver(
                "claude_code", LABELS["claude_code"], local, timeout, check=local.problem
            )

    timeout = settings.codex_timeout_seconds
    if not enabled("codex"):
        drivers["codex"] = off("codex", "switched_off", timeout)
    else:
        from app.agents import codex_model

        executable = (find_codex or codex_model.find_codex)()
        if executable is None:
            drivers["codex"] = off("codex", "codex_not_installed", timeout)
        else:
            codex = codex_model.CodexModel(executable, model=settings.codex_model)
            drivers["codex"] = Driver("codex", LABELS["codex"], codex, timeout, check=codex.problem)

    return drivers


def default_driver(drivers: Mapping[str, Driver]) -> Driver | None:
    """The driver a seat gets when it only says "a model"."""
    return next((drivers[name] for name in DRIVER_IDS if drivers.get(name, _NONE).available), None)


def narrator_driver(drivers: Mapping[str, Driver]) -> Driver | None:
    return next((drivers[name] for name in API_DRIVERS if drivers.get(name, _NONE).available), None)


_NONE = Driver("", "", None, 0.0)
