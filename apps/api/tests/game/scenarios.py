"""Helpers that drive the engine through common situations.

They read the full secret state on purpose: a test needs to put a known evil
player on a team to make a mission fail.
"""

from __future__ import annotations

from app.game.actions import Action, ProposeTeam, Speak, StartGame, VoteMission, VoteTeam
from app.game.engine import apply_action, new_game
from app.game.rulesets import OFFICIAL, Alignment, Role, RuleSet
from app.game.state import GameState, MissionOutcome, Phase


def player_ids(player_count: int) -> tuple[str, ...]:
    return tuple(f"p{number}" for number in range(1, player_count + 1))


def lobby(player_count: int = 5, ruleset: RuleSet = OFFICIAL) -> GameState:
    ids = player_ids(player_count)
    return new_game(game_id="game-1", ruleset=ruleset, player_ids=ids, host_id=ids[0])


def act(state: GameState, action: Action) -> GameState:
    return apply_action(state, action)[0]


def started(player_count: int = 5, seed: int = 1, ruleset: RuleSet = OFFICIAL) -> GameState:
    state = lobby(player_count, ruleset)
    return act(state, StartGame(player_id=state.host_id, seed=seed))


def leader_id(state: GameState) -> str:
    assert state.leader_id is not None
    return state.leader_id


def ids_with_alignment(state: GameState, alignment: Alignment) -> tuple[str, ...]:
    return tuple(
        player.id
        for player in state.players
        if player.role is not None and player.role.alignment is alignment
    )


def id_with_role(state: GameState, role: Role) -> str:
    return next(player.id for player in state.players if player.role is role)


def default_team(state: GameState) -> tuple[str, ...]:
    return state.player_ids[: state.current_mission.team_size]


def team_with_evil(state: GameState, evil_members: int) -> tuple[str, ...]:
    team_size = state.current_mission.team_size
    evil = ids_with_alignment(state, Alignment.EVIL)[:evil_members]
    good = ids_with_alignment(state, Alignment.GOOD)[: team_size - evil_members]
    assert len(evil) + len(good) == team_size
    return (*evil, *good)


def propose_only(state: GameState, team: tuple[str, ...] | None = None) -> GameState:
    """The leader names a team; the table has not discussed it yet."""
    team = default_team(state) if team is None else team
    return act(state, ProposeTeam(player_id=leader_id(state), team=team))


def discuss(state: GameState) -> GameState:
    """Everyone who has not spoken yet passes, in speaking order."""
    while state.phase is Phase.DISCUSSION:
        assert state.next_speaker_id is not None
        state = act(state, Speak(player_id=state.next_speaker_id))
    return state


def propose(state: GameState, team: tuple[str, ...] | None = None) -> GameState:
    """Propose a team and let the discussion pass, leaving the table ready to vote."""
    return discuss(propose_only(state, team))


def vote_team(state: GameState, *, approve: bool) -> GameState:
    """Every player casts the same vote."""
    for player_id in state.player_ids:
        state = act(state, VoteTeam(player_id=player_id, approve=approve))
    return state


def approve_team(state: GameState, team: tuple[str, ...] | None = None) -> GameState:
    return vote_team(propose(state, team), approve=True)


def reject_team(state: GameState) -> GameState:
    return vote_team(propose(state), approve=False)


def play_mission_cards(state: GameState, *, fails: int = 0) -> GameState:
    """Every team member plays a card; the first `fails` evil members play fail."""
    evil = set(ids_with_alignment(state, Alignment.EVIL))
    remaining = fails
    for player_id in state.current_mission.team:
        plays_fail = player_id in evil and remaining > 0
        remaining -= plays_fail
        state = act(state, VoteMission(player_id=player_id, success=not plays_fail))
    assert remaining == 0, "the team did not have enough evil players"
    return state


def complete_mission(state: GameState, outcome: MissionOutcome) -> GameState:
    """Approve a suitable team on the first proposal and play the mission to `outcome`."""
    fails = state.current_mission.fails_required if outcome is MissionOutcome.FAIL else 0
    state = approve_team(state, team_with_evil(state, fails))
    return play_mission_cards(state, fails=fails)


def complete_missions(state: GameState, *outcomes: MissionOutcome) -> GameState:
    for outcome in outcomes:
        state = complete_mission(state, outcome)
    return state
