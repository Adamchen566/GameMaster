"""Shared FastAPI dependencies: the service instance and authentication."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.errors import ApiError
from app.config import get_settings
from app.service import GameService, Session
from app.storage.database import Database
from app.storage.games import SqlGameRepository
from app.storage.rooms import SqlRoomStore


def build_service(database_url: str | None) -> GameService:
    """With a database URL games survive a restart; without one they live in memory."""
    if database_url is None:
        return GameService()

    database = Database.from_url(database_url)
    return GameService(
        SqlGameRepository(database),
        SqlRoomStore(database),
        transaction=database.transaction,
    )


@lru_cache
def get_service() -> GameService:
    """One service per process, built on first use."""
    return build_service(get_settings().database_url)


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
