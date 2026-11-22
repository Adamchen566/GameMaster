"""The v0.4 acceptance test: stop the server mid-game, start it again, and the
same token returns to the same game, which can then be played to the end."""

from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.api.deps import build_service, get_service
from app.game.state import Phase
from app.main import app
from app.storage.database import Database
from app.storage.games import SqlGameRepository
from tests.api.conftest import Backend, Seat, start_game, take_turn


@contextmanager
def running_server(url: str) -> Iterator[TestClient]:
    """A server process, as far as storage is concerned: a brand-new service."""
    service = build_service(url)
    app.dependency_overrides[get_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _backend(client: TestClient) -> Backend:
    return Backend(client=client, games=None, rooms=None)  # type: ignore[arg-type]


def test_game_continues_after_the_server_restarts(url: str) -> None:
    rng = random.Random(7)

    with running_server(url) as client:
        seat = start_game(_backend(client), player_count=7)
        # The human votes on every proposal and a game needs three missions, so
        # no game can be over after two human turns, whatever the server's seed.
        for _ in range(2):
            take_turn(seat, rng)
        before = seat.game
        game_id, token = seat.game_id, seat.token
    assert before["phase"] != "finished"

    with running_server(url) as client:
        resumed = Seat(client=client, game_id=game_id, token=token, game={})
        response = client.get(f"/games/{game_id}", headers=resumed.headers)

        assert response.status_code == 200, response.text
        assert response.json() == before

        resumed.game = response.json()
        while resumed.game["phase"] != "finished":
            take_turn(resumed, rng)
        final = resumed.game

    assert final["winner"] in {"good", "evil"}

    # What the client saw is what the log says happened.
    database = Database.from_url(url)
    repository = SqlGameRepository(database)
    stored = repository.load(game_id)
    assert stored.version == final["version"]
    assert stored.winner is not None and stored.winner.value == final["winner"]
    assert stored.phase is Phase.FINISHED
    assert len(repository.events(game_id)) == stored.version
    database.dispose()


def test_restarted_server_still_rejects_bad_tokens_and_unknown_games(url: str) -> None:
    with running_server(url) as client:
        seat = start_game(_backend(client))

    with running_server(url) as client:
        wrong = client.get(f"/games/{seat.game_id}", headers={"Authorization": "Bearer nope"})
        missing = client.get("/games/unknown", headers=seat.headers)

    assert wrong.status_code == 401
    assert missing.status_code == 404


def test_without_a_database_url_games_live_in_memory() -> None:
    first = build_service(None)
    created = first.create_room("Adam", 5)

    assert first.authenticate(created.token) is not None
    assert build_service(None).authenticate(created.token) is None
