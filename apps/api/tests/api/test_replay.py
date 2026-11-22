"""Replaying a finished game: every role, thought and model turn, once it is over."""

from __future__ import annotations

from tests.api.conftest import Backend, Seat, open_room


def watched_game(backend: Backend, player_count: int = 5) -> Seat:
    response = backend.client.post(
        "/rooms", json={"nickname": "Adam", "player_count": player_count, "spectate": True}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    seat = Seat(
        client=backend.client, game_id=body["game_id"], token=body["token"], game=body["game"]
    )
    seat.act(type="start_game")
    return seat


def test_a_finished_game_is_replayed_with_every_role_and_the_whole_record(
    backend: Backend,
) -> None:
    seat = watched_game(backend)

    response = backend.client.get(f"/games/{seat.game_id}/replay", headers=seat.headers)

    assert response.status_code == 200, response.text
    game = response.json()["game"]
    assert game["phase"] == "finished"
    assert all(player["role"] is not None for player in game["players"])
    assert game["log"][0]["kind"] == "mission_started"
    assert game["log"][-1]["kind"] == "game_finished"
    assert game["thoughts"], "the built-in bots' thoughts are part of the review"
    # Built-in bots are not model turns; a table of them has none to show.
    assert response.json()["turns"] == []


def test_a_game_still_being_played_cannot_be_replayed(backend: Backend) -> None:
    seat = open_room(backend)
    seat.act(type="start_game")

    response = backend.client.get(f"/games/{seat.game_id}/replay", headers=seat.headers)

    assert response.status_code == 409
    assert response.json()["code"] == "game_not_finished"


def test_a_replay_needs_the_token_of_that_game(backend: Backend) -> None:
    seat = watched_game(backend)
    other = watched_game(backend)

    assert backend.client.get(f"/games/{seat.game_id}/replay").status_code == 401
    wrong = backend.client.get(f"/games/{seat.game_id}/replay", headers=other.headers)
    assert wrong.status_code in (403, 404)


def test_a_big_table_can_be_replayed(backend: Backend) -> None:
    seat = watched_game(backend, 12)

    game = backend.client.get(f"/games/{seat.game_id}/replay", headers=seat.headers).json()["game"]

    assert len(game["players"]) == 12
    assert game["ruleset_id"] == "extended"
    assert game["evil_count"] == 5
