"""Whole-game properties: invariants, termination, determinism and replay."""

import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.game.actions import (
    Action,
    Assassinate,
    ProposeTeam,
    Speak,
    StartGame,
    VoteMission,
    VoteTeam,
)
from app.game.engine import apply_action, evolve, new_game, replay
from app.game.errors import RuleViolation
from app.game.rulesets import ruleset_for
from app.game.simulate import next_action as random_legal_action
from app.game.simulate import play_random_game
from app.game.state import GameState, Phase
from tests.game.invariants import check_invariants
from tests.game.scenarios import player_ids

# A game has at most 5 missions x 5 proposals x (1 proposal + 10 speeches + 10 votes)
# + 25 mission cards + start + assassination legal actions; junk is added on top.
MAX_STEPS = 650

SEEDS = st.integers(min_value=0, max_value=2**32 - 1)


def arbitrary_actions(ids: tuple[str, ...]) -> st.SearchStrategy[Action]:
    """Any well-typed action, legal or not, including ones from a stranger."""
    player = st.sampled_from([*ids, "ghost"])
    version = st.one_of(st.none(), st.none(), st.none(), st.integers(0, MAX_STEPS))
    return st.one_of(
        st.builds(StartGame, player_id=player, seed=SEEDS, expected_version=version),
        st.builds(
            ProposeTeam,
            player_id=player,
            team=st.lists(player, max_size=6).map(tuple),
            expected_version=version,
        ),
        st.builds(
            Speak,
            player_id=player,
            text=st.text(max_size=260),
            suspects=st.lists(player, max_size=4).map(tuple),
            expected_version=version,
        ),
        st.builds(VoteTeam, player_id=player, approve=st.booleans(), expected_version=version),
        st.builds(VoteMission, player_id=player, success=st.booleans(), expected_version=version),
        st.builds(Assassinate, player_id=player, target_id=player, expected_version=version),
    )


def step(state: GameState, action: Action) -> GameState:
    """Apply an action; a rule violation must leave the game exactly as it was."""
    try:
        new_state, events = apply_action(state, action)
    except RuleViolation:
        return state

    assert events
    assert new_state.version == state.version + len(events)
    check_invariants(new_state)
    return new_state


@settings(max_examples=75, deadline=None)
@given(data=st.data(), player_count=st.integers(5, 12), seed=SEEDS)
def test_no_sequence_of_actions_breaks_the_rules(
    data: st.DataObject, player_count: int, seed: int
) -> None:
    ids = player_ids(player_count)
    state = new_game(
        game_id="prop", ruleset=ruleset_for(player_count), player_ids=ids, host_id=ids[0]
    )
    junk = data.draw(st.lists(arbitrary_actions(ids), max_size=40))
    rng = random.Random(seed)
    check_invariants(state)

    steps = 0
    while state.phase is not Phase.FINISHED:
        steps += 1
        assert steps <= MAX_STEPS + 40, "the game must always reach an end"

        action: Action
        if junk and rng.random() < 0.4:
            action = junk.pop()
        elif state.phase is Phase.LOBBY:
            action = StartGame(player_id=ids[0], seed=seed)
        else:
            action = random_legal_action(state, rng)
        state = step(state, action)

    for action in junk:
        assert step(state, action) is state, "a finished game accepts nothing"


PLAYER_COUNTS = range(5, 13)


@pytest.mark.parametrize("player_count", PLAYER_COUNTS)
def test_random_games_finish_and_replay_to_the_same_state(player_count: int) -> None:
    for seed in range(40):
        game = play_random_game(player_count=player_count, seed=seed)

        assert game.final.phase is Phase.FINISHED
        assert game.final.version == len(game.events)
        assert replay(game.initial, game.events) == game.final
        check_invariants(game.final)


@pytest.mark.parametrize("player_count", PLAYER_COUNTS)
def test_the_same_seed_always_plays_the_same_game(player_count: int) -> None:
    first = play_random_game(player_count=player_count, seed=2026)
    second = play_random_game(player_count=player_count, seed=2026)

    assert first.events == second.events
    assert first.final == second.final


def test_different_seeds_play_different_games() -> None:
    games = {play_random_game(player_count=7, seed=seed).events for seed in range(10)}

    assert len(games) > 1


def test_every_event_advances_the_version_by_one() -> None:
    game = play_random_game(player_count=8, seed=5)

    state = game.initial
    for expected_version, event in enumerate(game.events, start=1):
        state = evolve(state, event)
        assert state.version == expected_version

    assert state == game.final
