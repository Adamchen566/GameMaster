import random
from typing import get_args

import pytest

from app.game.events import GameEvent
from app.game.simulate import format_event, main, next_action, play_random_game
from tests.game.scenarios import lobby


def test_no_random_action_exists_before_the_game_starts() -> None:
    with pytest.raises(ValueError, match="No player can act"):
        next_action(lobby(), random.Random(0))


def test_no_random_action_exists_after_the_game_ends() -> None:
    finished = play_random_game(player_count=5, seed=1).final

    with pytest.raises(ValueError, match="No player can act"):
        next_action(finished, random.Random(0))


def test_every_event_type_can_be_printed() -> None:
    seen: set[type] = set()
    for player_count in range(5, 11):
        for seed in range(30):
            for event in play_random_game(player_count=player_count, seed=seed).events:
                assert format_event(event).startswith(type(event).__name__)
                seen.add(type(event))

    assert seen == set(get_args(GameEvent))


def test_unknown_event_cannot_be_printed() -> None:
    with pytest.raises(TypeError, match="Unsupported event type"):
        format_event(object())  # type: ignore[arg-type]


def test_cli_prints_a_numbered_transcript_that_ends_with_the_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--players", "6", "--seed", "9"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Rule set: official, players: 6, seed: 9"
    assert lines[1].split()[:2] == ["1", "GameStarted"]
    assert lines[2].split()[:2] == ["2", "MissionStarted"]
    assert "GameFinished" in lines[-1]
    assert " wins (" in lines[-1]


def test_cli_prints_the_same_game_for_the_same_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["--players", "7", "--seed", "3"])
    first = capsys.readouterr().out
    main(["--players", "7", "--seed", "3"])
    second = capsys.readouterr().out

    assert first == second
