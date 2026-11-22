"""Shared FastAPI dependencies: the service instance and authentication."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.agents.drivers import Driver, build_drivers, default_driver, narrator_driver
from app.agents.llm_player import STYLES, LlmPlayer
from app.agents.model import ModelClient, Pricing, TokenBudget
from app.api.errors import ApiError
from app.config import Settings, get_settings
from app.gm.narrator import Narrator
from app.service import UNMETERED_TOKENS, Executor, GameService, Session
from app.storage.agent_states import SqlAgentStateStore
from app.storage.database import Database
from app.storage.games import SqlGameRepository
from app.storage.rooms import SqlRoomStore
from app.storage.thoughts import SqlThoughtStore
from app.storage.turns import SqlTurnStore

MEMORY = "memory"
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def build_ai(settings: Settings, model: ModelClient | None = None) -> dict[str, Any]:
    """The AI-related arguments of `GameService`.

    `model` replaces every provider with one client, for tests and scripts.
    """
    if model is not None:
        only = Driver("claude", "Claude", model, settings.llm_player_timeout_seconds)
        drivers = {"claude": only}
        seat_driver: Driver | None = only
        narrator_model: ModelClient | None = model
    else:
        drivers = build_drivers(settings)
        seat_driver = default_driver(drivers)
        voice = narrator_driver(drivers)
        narrator_model = voice.model if voice is not None else None
    if seat_driver is None or seat_driver.model is None:
        # Still passed on, so the lobby can say what each driver is missing.
        return {"drivers": drivers}

    input_price, output_price = (
        settings.llm_input_price_per_mtok,
        settings.llm_output_price_per_mtok,
    )
    pricing = (
        Pricing(input_price, output_price)
        if input_price is not None and output_price is not None
        else None
    )
    budget = TokenBudget(settings.llm_max_tokens_per_game, pricing)
    # The default model of seats made without a choice: only a paid API is held to the ceiling.
    seat_budget = budget if seat_driver.metered else TokenBudget(UNMETERED_TOKENS)
    return {
        "budget": budget,
        "drivers": drivers,
        "llm_players": {
            style: LlmPlayer(
                seat_driver.model,
                seat_budget,
                style=style,
                timeout_seconds=seat_driver.timeout_seconds,
            )
            for style in STYLES
        },
        "narrator": (
            Narrator(narrator_model, budget, timeout_seconds=settings.llm_gm_timeout_seconds)
            if narrator_model is not None
            else Narrator()
        ),
    }


def build_service(
    database_url: str | None,
    settings: Settings | None = None,
    *,
    model: ModelClient | None = None,
    executor: Executor | None = None,
) -> GameService:
    """With a database URL games survive a restart; without one ("memory") they do not."""
    ai = build_ai(settings or Settings(), model)
    if database_url is None or database_url == MEMORY:
        return GameService(executor=executor, **ai)

    database = Database.from_url(database_url)
    return GameService(
        SqlGameRepository(database),
        SqlRoomStore(database),
        transaction=database.transaction,
        agent_states=SqlAgentStateStore(database),
        thoughts=SqlThoughtStore(database),
        turns=SqlTurnStore(database),
        executor=executor,
        **ai,
    )


@lru_cache
def get_service() -> GameService:
    """One service per process, built on first use."""
    settings = get_settings()
    if settings.auto_migrate and settings.database_url != MEMORY:
        migrate(settings.database_url)
    return build_service(settings.database_url, settings)


def migrate(url: str) -> None:
    """Create the database (a SQLite file and its folder) and bring the schema up to date."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    if not MIGRATIONS.is_dir():
        return
    # No ini file: the API's own logging setup must stay as it is.
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")


def database_for(settings: Settings) -> Database | None:
    """The configured database, migrated; None when games live in memory."""
    if settings.database_url == MEMORY:
        return None
    migrate(settings.database_url)
    return Database.from_url(settings.database_url)


ServiceDep = Annotated[GameService, Depends(get_service)]

_bearer = HTTPBearer(auto_error=False)


def current_session(
    game_id: str,
    service: ServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Session:
    """Resolve the bearer token to a seat in the requested game."""
    if credentials is None:
        raise ApiError(401, "missing_token", "Send the reconnect token as a Bearer token.")

    session = service.authenticate(credentials.credentials)
    if session is None:
        raise ApiError(401, "invalid_token", "This token is not valid.")

    # Only authenticated callers learn whether a game exists.
    if service.find_room(game_id) is None:
        raise ApiError(404, "game_not_found", "This game does not exist.")
    if session.room.game_id != game_id:
        raise ApiError(403, "wrong_game", "This token belongs to a different game.")
    return session


SessionDep = Annotated[Session, Depends(current_session)]
