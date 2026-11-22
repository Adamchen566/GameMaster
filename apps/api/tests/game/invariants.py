"""Properties that must hold for every state the engine can produce."""

from __future__ import annotations

from app.game.rulesets import Alignment, Role
from app.game.state import GameState, MissionOutcome, Phase, WinReason

_PLAY_PHASES = {Phase.TEAM_PROPOSAL, Phase.TEAM_VOTE, Phase.MISSION_VOTE}


def check_invariants(state: GameState) -> None:
    ruleset = state.ruleset
    ids = set(state.player_ids)
    player_count = len(state.players)

    assert len(ids) == player_count
    assert [player.seat for player in state.players] == list(range(player_count))

    # Neither side can score more missions than it needs to win, and never both.
    successes = state.successful_missions
    failures = state.failed_missions
    assert successes <= ruleset.missions_to_win
    assert failures <= ruleset.missions_to_win
    assert not (successes == ruleset.missions_to_win and failures == ruleset.missions_to_win)

    assert 0 <= state.rejected_proposals <= ruleset.max_rejected_proposals

    finished = state.phase is Phase.FINISHED
    assert (state.winner is not None) == finished
    assert (state.win_reason is not None) == finished

    if state.phase is Phase.LOBBY:
        assert state.version == 0
        assert all(player.role is None for player in state.players)
        assert state.missions == ()
        assert state.leader_id is None
        return

    rules = ruleset.for_players(player_count)
    assert sorted(player.role for player in state.players) == sorted(rules.roles)

    # There is exactly one leader and it is a seated player.
    assert state.leader_id in ids

    # Completed missions form a prefix and their recorded result is consistent.
    outcomes = [mission.outcome for mission in state.missions]
    completed = sum(outcome is not None for outcome in outcomes)
    assert all(outcome is not None for outcome in outcomes[:completed])
    assert all(outcome is None for outcome in outcomes[completed:])
    for mission in state.missions[:completed]:
        assert len(set(mission.team)) == mission.team_size
        assert set(mission.team) <= ids
        assert mission.fail_votes is not None
        failed = mission.fail_votes >= mission.fails_required
        assert (mission.outcome is MissionOutcome.FAIL) == failed

    if state.phase in _PLAY_PHASES:
        assert state.mission_index == completed
        assert successes < ruleset.missions_to_win
        assert failures < ruleset.missions_to_win
        assert state.rejected_proposals < ruleset.max_rejected_proposals

    mission = state.missions[state.mission_index]

    if state.phase is Phase.TEAM_VOTE:
        assert len(set(state.proposed_team)) == mission.team_size
        assert set(state.proposed_team) <= ids
        voters = [vote.player_id for vote in state.team_votes]
        assert len(set(voters)) == len(voters) < player_count
        assert set(voters) <= ids
    else:
        assert state.proposed_team == ()
        assert state.team_votes == ()

    if state.phase is Phase.MISSION_VOTE:
        assert len(set(mission.team)) == mission.team_size
        voters = [vote.player_id for vote in state.mission_votes]
        assert len(set(voters)) == len(voters) < mission.team_size
        assert set(voters) <= set(mission.team)
        good = {p.id for p in state.players if p.role.alignment is Alignment.GOOD}
        assert all(vote.success for vote in state.mission_votes if vote.player_id in good)
    else:
        assert state.mission_votes == ()

    if state.phase is Phase.ASSASSINATION:
        assert ruleset.assassination_enabled
        assert successes == ruleset.missions_to_win
        assert state.assassination_target_id is None

    if finished:
        _check_ending(state, successes, failures)


def _check_ending(state: GameState, successes: int, failures: int) -> None:
    ruleset = state.ruleset
    target = (
        state.find_player(state.assassination_target_id)
        if state.assassination_target_id is not None
        else None
    )
    match state.win_reason:
        case WinReason.MISSIONS_FAILED:
            assert state.winner is Alignment.EVIL
            assert failures == ruleset.missions_to_win
        case WinReason.PROPOSALS_REJECTED:
            assert state.winner is Alignment.EVIL
            assert state.rejected_proposals == ruleset.max_rejected_proposals
        case WinReason.MERLIN_ASSASSINATED:
            assert state.winner is Alignment.EVIL
            assert successes == ruleset.missions_to_win
            assert target is not None and target.role is Role.MERLIN
        case WinReason.MERLIN_SURVIVED:
            assert state.winner is Alignment.GOOD
            assert successes == ruleset.missions_to_win
            assert target is not None and target.role is not Role.MERLIN
        case WinReason.MISSIONS_SUCCEEDED:
            assert state.winner is Alignment.GOOD
            assert successes == ruleset.missions_to_win
            assert not ruleset.assassination_enabled
        case _:
            raise AssertionError(f"unexpected win reason {state.win_reason!r}")
