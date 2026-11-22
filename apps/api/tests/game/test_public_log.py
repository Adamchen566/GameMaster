import json

import pytest

from app.game.events import GameStarted, MissionVoteCast, TeamVoteCast
from app.game.public_log import public_log
from app.game.rulesets import Role
from app.game.simulate import play_random_game

PUBLIC_KINDS = {
    "mission_started",
    "team_proposed",
    "speech",
    "team_vote",
    "mission_result",
    "assassination_started",
    "assassination",
    "game_finished",
}


@pytest.mark.parametrize("player_count", range(5, 11))
def test_log_never_mentions_a_role_the_seed_or_a_single_mission_card(player_count: int) -> None:
    kinds: set[str] = set()
    for seed in range(20):
        game = play_random_game(player_count=player_count, seed=seed)
        log = public_log(game.events)
        text = json.dumps([entry.to_json() for entry in log])

        # Values only: "assassin" is also the name of a public field.
        values = [str(value) for entry in log for value in entry.data.values()]
        assert not {role.value for role in Role} & set(values)
        assert "seed" not in text
        assert 'success": true' not in text and 'success": false' not in text
        kinds |= {entry.kind for entry in log}

    assert kinds <= PUBLIC_KINDS


def test_all_public_kinds_occur_across_games() -> None:
    kinds = {
        entry.kind
        for seed in range(40)
        for entry in public_log(play_random_game(player_count=7, seed=seed).events)
    }

    assert kinds == PUBLIC_KINDS


def test_secret_events_are_dropped_but_keep_their_place_in_the_numbering() -> None:
    game = play_random_game(player_count=5, seed=1)
    log = public_log(game.events)

    secret = (GameStarted, TeamVoteCast, MissionVoteCast)
    expected_versions = [
        version
        for version, event in enumerate(game.events, start=1)
        if not isinstance(event, secret)
    ]
    assert [entry.version for entry in log] == expected_versions
    assert log[-1].kind == "game_finished"
    assert log[-1].version == len(game.events)


def test_team_vote_shows_who_voted_how_because_that_is_public_in_avalon() -> None:
    game = play_random_game(player_count=5, seed=1)
    vote = next(entry for entry in public_log(game.events) if entry.kind == "team_vote")

    assert sorted([*vote.data["approvals"], *vote.data["rejections"]]) == [  # type: ignore[misc]
        "p1",
        "p2",
        "p3",
        "p4",
        "p5",
    ]


def test_mission_result_shows_the_count_of_fails_only() -> None:
    game = play_random_game(player_count=5, seed=1)
    result = next(entry for entry in public_log(game.events) if entry.kind == "mission_result")

    assert set(result.data) == {"mission", "outcome", "fail_votes"}


def test_a_later_slice_can_be_numbered_from_its_first_version() -> None:
    game = play_random_game(player_count=5, seed=1)

    tail = public_log(game.events[10:], first_version=11)

    assert tail == tuple(entry for entry in public_log(game.events) if entry.version >= 11)


def test_entries_cannot_be_modified() -> None:
    entry = public_log(play_random_game(player_count=5, seed=1).events)[0]

    with pytest.raises(TypeError):
        entry.data["leader"] = "p9"  # type: ignore[index]
