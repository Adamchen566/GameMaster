import random

import pytest

from app.agents.policy_fallback import choose_action
from app.game.engine import apply_action
from app.game.rulesets import Alignment, Role
from app.game.state import GameState, MissionOutcome, Phase
from app.game.views import build_player_view
from tests.game.invariants import check_invariants
from tests.game.scenarios import (
    complete_missions,
    id_with_role,
    ids_with_alignment,
    lobby,
    started,
)

SUCCESS = MissionOutcome.SUCCESS


def bot_to_act(state: GameState) -> str:
    return next(
        player_id
        for player_id in state.player_ids
        if build_player_view(state, player_id).legal_actions
    )


def play_with_bots_only(player_count: int, seed: int) -> GameState:
    rng = random.Random(seed)
    state = started(player_count, seed)
    while state.phase is not Phase.FINISHED:
        view = build_player_view(state, bot_to_act(state))
        action = choose_action(view, rng)
        assert action.expected_version == state.version
        state, _ = apply_action(state, action)
        check_invariants(state)
    return state


@pytest.mark.parametrize("player_count", range(5, 11))
def test_bots_finish_a_game_using_only_their_own_views(player_count: int) -> None:
    for seed in range(15):
        final = play_with_bots_only(player_count, seed)

        assert final.phase is Phase.FINISHED
        assert final.winner is not None


def test_bot_games_end_in_more_than_one_way() -> None:
    reasons = {play_with_bots_only(7, seed).win_reason for seed in range(40)}

    assert len(reasons) > 1


def test_same_random_stream_makes_the_same_choice() -> None:
    state = started(seed=5)
    view = build_player_view(state, bot_to_act(state))

    assert choose_action(view, random.Random(9)) == choose_action(view, random.Random(9))


def test_bot_with_nothing_to_do_is_an_error() -> None:
    state = started()
    idle = next(pid for pid in state.player_ids if pid != state.leader_id)

    with pytest.raises(ValueError, match="nothing to do"):
        choose_action(build_player_view(state, idle), random.Random(0))


def test_assassin_bot_never_targets_a_player_it_knows_is_evil() -> None:
    state = complete_missions(started(10), SUCCESS, SUCCESS, SUCCESS)
    assassin = id_with_role(state, Role.ASSASSIN)
    evil = set(ids_with_alignment(state, Alignment.EVIL))
    view = build_player_view(state, assassin)

    targets = {choose_action(view, random.Random(seed)).target_id for seed in range(60)}  # type: ignore[union-attr]

    assert targets
    assert targets.isdisjoint(evil)


def test_bot_never_starts_a_game() -> None:
    host_view = build_player_view(lobby(), "p1")

    with pytest.raises(ValueError, match="cannot perform 'start_game'"):
        choose_action(host_view, random.Random(0))
