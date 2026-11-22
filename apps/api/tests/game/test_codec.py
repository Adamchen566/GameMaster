import json

import pytest

from app.game.codec import EVENT_TYPES, decode_event, encode_event
from app.game.events import GameStarted, TeamProposed
from app.game.rulesets import Role
from app.game.simulate import play_random_game


def _through_json(value: object) -> object:
    return json.loads(json.dumps(value))


def test_every_event_of_many_games_survives_a_round_trip_through_json() -> None:
    seen: set[str] = set()

    for player_count in range(5, 11):
        for seed in range(25):
            for event in play_random_game(player_count=player_count, seed=seed).events:
                event_type, payload = encode_event(event)
                seen.add(event_type)

                stored = _through_json(payload)
                assert isinstance(stored, dict)
                assert decode_event(event_type, stored) == event

    # Otherwise an event type could be broken without this test noticing.
    assert seen == EVENT_TYPES


def test_payload_is_plain_data_without_the_type_name() -> None:
    event = GameStarted(seed=7, roles=(("p1", Role.MERLIN), ("p2", Role.ASSASSIN)))

    assert encode_event(event) == (
        "game_started",
        {"seed": 7, "roles": [["p1", "merlin"], ["p2", "assassin"]]},
    )


def test_decoding_restores_tuples_and_enums() -> None:
    event = decode_event("game_started", {"seed": 7, "roles": [["p1", "merlin"]]})

    assert event == GameStarted(seed=7, roles=(("p1", Role.MERLIN),))
    assert isinstance(event, GameStarted)
    assert event.roles[0][1] is Role.MERLIN


def test_unknown_event_type_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown event type 'game_paused'"):
        decode_event("game_paused", {})


def test_missing_field_is_refused() -> None:
    with pytest.raises(KeyError):
        decode_event("team_vote_cast", {"player_id": "p1"})


def test_unknown_enum_value_is_refused() -> None:
    with pytest.raises(ValueError):
        decode_event("game_finished", {"winner": "nobody", "reason": "missions_failed"})


def test_player_list_must_be_a_list() -> None:
    with pytest.raises(TypeError, match="list of player ids"):
        decode_event(
            "team_proposed",
            {"mission_number": 1, "proposal_number": 1, "leader_id": "p1", "team": "p1"},
        )


def test_team_is_decoded_as_a_tuple() -> None:
    event = decode_event(
        "team_proposed",
        {"mission_number": 1, "proposal_number": 1, "leader_id": "p1", "team": ["p1", "p2"]},
    )

    assert event == TeamProposed(
        mission_number=1, proposal_number=1, leader_id="p1", team=("p1", "p2")
    )
