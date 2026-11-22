"""Runtime settings, read from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # A local, git-ignored `.env` next to the app is the easiest place for keys.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = None
    """SQLAlchemy URL, e.g. `postgresql+psycopg://user:password@host:5432/avalon`.

    Unset means games live in memory and are lost when the process stops.
    """

    llm_provider: Literal["none", "anthropic"] = "none"
    """Set to "anthropic" to allow model-driven seats and the AI game master.

    Credentials are read by the SDK itself (ANTHROPIC_API_KEY). Every AI turn is a paid call.
    """
    llm_drivers: str = "auto"
    """Which ways of reaching a model to offer: "auto" (whatever is set up), "none",
    or a comma list of `claude`, `deepseek`, `claude_code`, `codex`."""
    anthropic_api_key: str | None = None
    """Enables Claude seats. Every turn is a paid call."""
    deepseek_api_key: str | None = None
    """Enables DeepSeek seats. Every turn is a paid call."""
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout_seconds: float = 30.0
    claude_code_model: str = "sonnet"
    """Model alias passed to the local Claude Code client."""
    claude_code_timeout_seconds: float = 120.0
    codex_model: str | None = None
    """Model passed to the local Codex client; unset is Codex's own default."""
    codex_timeout_seconds: float = 120.0
    """One run of the local client takes many seconds."""
    llm_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    llm_max_tokens_per_game: int = 300_000
    """Input plus output tokens. A game that has used this many plays its AI seats as bots."""
    llm_player_timeout_seconds: float = 8.0
    llm_gm_timeout_seconds: float = 3.0
    llm_input_price_per_mtok: float | None = None
    llm_output_price_per_mtok: float | None = None
    """US dollars per million tokens; set both to see an estimated cost per game."""

    log_format: Literal["json", "text"] = "json"
    """One JSON object per line, or plain text for reading in a terminal."""
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
