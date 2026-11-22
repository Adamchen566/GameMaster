"""Runtime settings, read from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str | None = None
    """SQLAlchemy URL, e.g. `postgresql+psycopg://user:password@host:5432/avalon`.

    Unset means games live in memory and are lost when the process stops.
    """


@lru_cache
def get_settings() -> Settings:
    return Settings()
