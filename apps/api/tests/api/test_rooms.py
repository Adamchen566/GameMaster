import pytest

from app.rooms import hash_token
from tests.api.conftest import Backend, open_room


def test_creating_a_room_seats_you_as_host_and_fills_the_rest_with_bots(backend: Backend) -> None:
    response = backend.client.post("/rooms", json={"nickname": "Adam", "player_count": 7})

    assert response.status_code == 201
    body = response.json()
    game = body["game"]
    assert len(body["room_code"]) == 6
    assert body["room_code"] == game["room_code"]
    assert body["player_id"] == game["you_id"]
    assert game["phase"] == "lobby"
    assert game["version"] == 0
    assert len(game["players"]) == 7

    humans = [player for player in game["players"] if not player["is_bot"]]
    assert len(humans) == 1
    assert humans[0]["name"] == "Adam"
    assert humans[0]["is_you"] is True
    assert humans[0]["is_host"] is True
    assert len({player["name"] for player in game["players"]}) == 7
    assert all(player["role"] is None for player in game["players"])
    assert [action["type"] for action in game["legal_actions"]] == ["start_game"]


def test_nickname_is_trimmed(backend: Backend) -> None:
    seat = open_room(backend, nickname="  Adam  ")

    assert seat.me["name"] == "Adam"


@pytest.mark.parametrize(
    "payload",
    [
        {"nickname": "   ", "player_count": 5},
        {"nickname": "x" * 21, "player_count": 5},
        {"nickname": "Adam"},
        {"player_count": 5},
        {"nickname": "Adam", "player_count": "many"},
    ],
)
def test_malformed_room_request_is_rejected(backend: Backend, payload: dict[str, object]) -> None:
    assert backend.client.post("/rooms", json=payload).status_code == 422


@pytest.mark.parametrize("player_count", [1, 4, 13])
def test_room_needs_a_supported_player_count(backend: Backend, player_count: int) -> None:
    response = backend.client.post(
        "/rooms", json={"nickname": "Adam", "player_count": player_count}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_player_count"


def test_only_a_digest_of_the_token_is_stored(backend: Backend) -> None:
    seat = open_room(backend)

    room = backend.rooms.by_game_id(seat.game_id)
    assert room is not None
    stored = [s.token_hash for s in room.seats if s.token_hash is not None]
    assert stored == [hash_token(seat.token)]
    assert seat.token not in stored
    assert len(stored[0]) == 64


def test_each_room_gets_its_own_game_and_token(backend: Backend) -> None:
    first = open_room(backend)
    second = open_room(backend)

    assert first.game_id != second.game_id
    assert first.token != second.token
    assert first.game["room_code"] != second.game["room_code"]


def test_token_is_only_returned_when_the_room_is_created(backend: Backend) -> None:
    seat = open_room(backend)

    later = backend.client.get(f"/games/{seat.game_id}", headers=seat.headers)

    assert later.status_code == 200
    assert seat.token not in later.text
    assert "token" not in later.json()
