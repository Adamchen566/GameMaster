import random

import pytest

from app.api.errors import status_for
from app.game.engine import replay
from app.game.errors import ErrorCode
from tests.api.conftest import (
    Backend,
    Game,
    Seat,
    isolated_backend,
    open_room,
    play_until,
    start_game,
    take_turn,
)

# --- Authentication ----------------------------------------------------------


def test_game_requires_a_token(backend: Backend) -> None:
    seat = open_room(backend)

    response = backend.client.get(f"/games/{seat.game_id}")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_token"


def test_unknown_token_is_rejected(backend: Backend) -> None:
    seat = open_room(backend)

    response = backend.client.get(
        f"/games/{seat.game_id}", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_token"


def test_token_for_another_game_is_forbidden(backend: Backend) -> None:
    mine = open_room(backend)
    other = open_room(backend)

    read = backend.client.get(f"/games/{other.game_id}", headers=mine.headers)
    write = backend.client.post(
        f"/games/{other.game_id}/actions", json={"type": "start_game"}, headers=mine.headers
    )

    assert read.status_code == write.status_code == 403
    assert read.json()["code"] == "wrong_game"
    assert other.client.get(f"/games/{other.game_id}", headers=other.headers).json()["phase"] == (
        "lobby"
    )


def test_unknown_game_is_not_found_for_an_authenticated_player(backend: Backend) -> None:
    seat = open_room(backend)

    response = backend.client.get("/games/does-not-exist", headers=seat.headers)

    assert response.status_code == 404
    assert response.json()["code"] == "game_not_found"


def test_player_can_read_their_own_game(backend: Backend) -> None:
    seat = open_room(backend)

    response = backend.client.get(f"/games/{seat.game_id}", headers=seat.headers)

    assert response.status_code == 200
    assert response.json() == seat.game


# --- Playing -----------------------------------------------------------------


def test_starting_the_game_deals_roles_and_lets_the_bots_play_up_to_your_turn(
    backend: Backend,
) -> None:
    seat = start_game(backend)
    game = seat.game

    assert game["phase"] in {"team_proposal", "discussion", "team_vote"}
    assert game["version"] >= 2
    assert seat.me["role"] is not None
    assert seat.me["alignment"] in {"good", "evil"}
    assert seat.legal is not None, "the game must be waiting for the human"
    if game["phase"] == "team_proposal":
        assert seat.me["is_leader"] is True
    else:
        # A bot leader has proposed and the table has talked up to the human's seat.
        assert len(game["proposed_team"]) == game["missions"][0]["team_size"]
        assert game["speeches"][0]["player_id"] == game["leader_id"]
        if game["phase"] == "discussion":
            assert game["speaker_id"] == game["you_id"]
            assert seat.legal["type"] == "speak"
        else:
            # Everyone has spoken and every bot has already voted.
            assert len(game["speeches"]) == len(game["players"])
            assert len(game["team_voted"]) == len(game["players"]) - 1


def test_reading_the_game_returns_the_same_view_as_the_last_action(backend: Backend) -> None:
    seat = start_game(backend)

    response = backend.client.get(f"/games/{seat.game_id}", headers=seat.headers)

    assert response.json() == seat.game


def test_action_in_the_wrong_phase_is_a_conflict(backend: Backend) -> None:
    seat = open_room(backend)

    response = seat.post(type="vote_mission", success=True)

    assert response.status_code == 409
    assert response.json()["code"] == "wrong_phase"


def test_action_made_for_an_old_version_is_a_conflict(backend: Backend) -> None:
    seat = open_room(backend)

    response = seat.post(type="start_game", expected_version=99)

    assert response.status_code == 409
    assert response.json()["code"] == "stale_version"
    assert seat.act(type="start_game", expected_version=0)["phase"] != "lobby"


def test_team_vote_during_a_mission_is_a_conflict(backend: Backend) -> None:
    seat = play_until(backend, lambda s: s.legal is not None and s.legal["type"] == "vote_mission")

    response = seat.post(type="vote_team", approve=True)

    assert response.status_code == 409
    assert response.json()["code"] == "wrong_phase"


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "dance"},
        {"type": "vote_team"},
        {"type": "vote_team", "approve": "yes"},
        {"type": "vote_mission", "success": 1},
        {"type": "propose_team", "team": "p1"},
        {"type": "assassinate"},
        {},
    ],
)
def test_malformed_action_is_rejected(backend: Backend, payload: dict[str, object]) -> None:
    seat = start_game(backend)

    assert seat.post(**payload).status_code == 422


def as_leader(backend: Backend) -> Seat:
    return play_until(backend, lambda s: s.legal is not None and s.legal["type"] == "propose_team")


def test_leader_must_propose_a_team_of_the_right_size(backend: Backend) -> None:
    seat = as_leader(backend)
    assert seat.legal is not None

    response = seat.post(type="propose_team", team=seat.legal["targets"])

    assert response.status_code == 422
    assert response.json()["code"] == "wrong_team_size"


def test_leader_cannot_propose_duplicates_or_strangers(backend: Backend) -> None:
    seat = as_leader(backend)

    duplicate = seat.post(type="propose_team", team=["p1", "p1"])
    stranger = seat.post(type="propose_team", team=["p1", "ghost"])

    assert (duplicate.status_code, duplicate.json()["code"]) == (422, "duplicate_team_member")
    assert (stranger.status_code, stranger.json()["code"]) == (422, "unknown_team_member")


def test_good_player_cannot_play_a_fail_card(backend: Backend) -> None:
    seat = play_until(
        backend,
        lambda s: (
            s.legal is not None and s.legal["type"] == "vote_mission" and not s.legal["can_fail"]
        ),
    )

    response = seat.post(type="vote_mission", success=False)

    assert response.status_code == 422
    assert response.json()["code"] == "good_must_succeed"


def test_rejected_action_leaves_the_game_unchanged(backend: Backend) -> None:
    seat = start_game(backend)
    before = seat.game

    assert seat.post(type="assassinate", target_id="p2").status_code == 409

    after = backend.client.get(f"/games/{seat.game_id}", headers=seat.headers).json()
    assert after == before


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (ErrorCode.NOT_HOST, 403),
        (ErrorCode.NOT_LEADER, 403),
        (ErrorCode.NOT_ON_TEAM, 403),
        (ErrorCode.NOT_ASSASSIN, 403),
        (ErrorCode.WRONG_PHASE, 409),
        (ErrorCode.STALE_VERSION, 409),
        (ErrorCode.ALREADY_VOTED, 409),
        (ErrorCode.WRONG_TEAM_SIZE, 422),
        (ErrorCode.INVALID_TARGET, 422),
        (ErrorCode.GOOD_MUST_SUCCEED, 422),
        (ErrorCode.INVALID_PLAYER_COUNT, 422),
    ],
)
def test_rule_violations_map_to_http_statuses(code: ErrorCode, status: int) -> None:
    assert status_for(code) == status


# --- Whole games -------------------------------------------------------------


def assert_nothing_secret_is_visible(seat: Seat) -> None:
    game = seat.game
    for player in game["players"]:
        if not player["is_you"]:
            assert player["role"] is None
            assert player["alignment"] is None
    if seat.me["role"] == "loyal_servant":
        assert all(player["seen_as"] is None for player in game["players"])
    assert "seed" not in game
    assert "token" not in game


@pytest.mark.parametrize("player_count", range(5, 11))
def test_one_human_and_bots_can_play_a_whole_game(backend: Backend, player_count: int) -> None:
    for attempt in range(3):
        seat = start_game(backend, player_count)
        rng = random.Random(attempt)

        turns = 0
        while seat.game["phase"] != "finished":
            assert_nothing_secret_is_visible(seat)
            take_turn(seat, rng)
            turns += 1
            assert turns < 200

        game = seat.game
        assert game["winner"] in {"good", "evil"}
        assert game["win_reason"] is not None
        assert game["legal_actions"] == []
        assert all(player["role"] is not None for player in game["players"])

        # What was stored is exactly what was played.
        stored = backend.games.load(seat.game_id)
        events = backend.games.events(seat.game_id)
        assert stored.version == game["version"] == len(events)
        assert stored.winner == game["winner"]


def test_stored_events_replay_to_the_stored_state(backend: Backend) -> None:
    seat = open_room(backend)
    lobby_state = backend.games.load(seat.game_id)
    seat.act(type="start_game")
    rng = random.Random(0)
    while seat.game["phase"] != "finished":
        take_turn(seat, rng)

    events = backend.games.events(seat.game_id)

    assert replay(lobby_state, events) == backend.games.load(seat.game_id)


def test_same_seed_and_same_choices_play_the_same_game() -> None:
    def play() -> list[Game]:
        # Every fresh backend hands out seed 1 first, so both runs share a seed.
        with isolated_backend() as backend:
            seat = start_game(backend)
            rng = random.Random(3)
            history = [seat.game]
            while seat.game["phase"] != "finished":
                history.append(take_turn(seat, rng))
        # Ids and room codes are random on purpose; everything else must match.
        return [{**game, "game_id": "", "room_code": ""} for game in history]

    first = play()
    second = play()

    assert first[-1]["phase"] == "finished"
    assert first == second


def test_openapi_document_lists_the_game_endpoints(backend: Backend) -> None:
    paths = backend.client.get("/openapi.json").json()["paths"]

    assert set(paths) >= {"/health", "/rooms", "/games/{game_id}", "/games/{game_id}/actions"}


def test_the_game_carries_the_public_record_for_the_client_to_replay(backend: Backend) -> None:
    seat = start_game(backend)
    game = seat.game
    log = game["log"]

    versions = [entry["version"] for entry in log]
    assert versions == sorted(set(versions))
    assert versions[-1] <= game["version"]
    assert log[0]["kind"] == "mission_started"
    # Only what is said out loud: never the deal, a single ballot or a mission card.
    assert {entry["kind"] for entry in log} <= {
        "mission_started",
        "team_proposed",
        "speech",
        "team_vote",
        "mission_result",
        "assassination_started",
        "assassination",
        "game_finished",
    }
    assert "role" not in str(log)
    spoken = [entry["player"] for entry in log if entry["kind"] == "speech"]
    assert spoken == [speech["player_id"] for speech in game["speeches"]]
