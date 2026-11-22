"""How storage failures reach the client."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.api.deps import get_service
from app.game.events import GameEvent
from app.game.repository import GameNotFound, InMemoryGameRepository, VersionConflict
from app.game.state import GameState
from app.main import app
from app.service import GameService


class _RacingRepository(InMemoryGameRepository):
    """Behaves as if another server process stored an event first."""

    def append(self, game_id: str, expected_version: int, events: Sequence[GameEvent]) -> GameState:
        raise VersionConflict(game_id, expected_version, expected_version + 1)


class _ForgetfulRepository(InMemoryGameRepository):
    """Behaves as if the game row disappeared while its room still exists."""

    def load(self, game_id: str) -> GameState:
        raise GameNotFound(game_id)


@contextmanager
def client_for(repository: InMemoryGameRepository) -> Iterator[TestClient]:
    service = GameService(repository)
    app.dependency_overrides[get_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_losing_a_race_to_another_writer_is_a_409_the_client_can_retry() -> None:
    with client_for(_RacingRepository()) as client:
        room = client.post("/rooms", json={"nickname": "Adam", "player_count": 5}).json()
        headers = {"Authorization": f"Bearer {room['token']}"}

        response = client.post(
            f"/games/{room['game_id']}/actions", json={"type": "start_game"}, headers=headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "stale_version"
        # Nothing was stored, so the game is still in the lobby.
        assert client.get(f"/games/{room['game_id']}", headers=headers).json()["phase"] == "lobby"


def test_game_missing_from_storage_is_a_404() -> None:
    with client_for(_ForgetfulRepository()) as client:
        room = client.post("/rooms", json={"nickname": "Adam", "player_count": 5}).json()

        response = client.get(
            f"/games/{room['game_id']}", headers={"Authorization": f"Bearer {room['token']}"}
        )

        assert response.status_code == 404
        assert response.json() == {"code": "game_not_found", "message": "This game does not exist."}
