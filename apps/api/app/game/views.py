"""Per-player views: the only way information leaves the engine.

`GameState` holds every secret. `build_player_view` copies out exactly what one
seat is allowed to know, plus the actions that seat may take right now. Clients,
bots and models are only ever given a view, never the state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.game.errors import ErrorCode, RuleViolation
from app.game.rulesets import Alignment, Role
from app.game.state import (
    GameState,
    MissionOutcome,
    Phase,
    PlayerState,
    TeamVoteRecord,
    WinReason,
)


class Knowledge(StrEnum):
    """What a role lets its owner know about another player."""

    EVIL = "evil"
    MERLIN_OR_MORGANA = "merlin_or_morgana"


@dataclass(frozen=True, slots=True)
class PlayerInfo:
    id: str
    seat: int
    role: Role | None
    """Your own role, or everyone's once the game is over."""
    alignment: Alignment | None
    seen_as: Knowledge | None
    """What your role reveals about this player while the game is running."""


@dataclass(frozen=True, slots=True)
class MissionInfo:
    number: int
    team_size: int
    fails_required: int
    team: tuple[str, ...]
    outcome: MissionOutcome | None
    fail_votes: int | None


@dataclass(frozen=True, slots=True)
class LegalAction:
    type: str
    """Matches the `type` of the action it allows, e.g. "propose_team"."""
    team_size: int | None = None
    targets: tuple[str, ...] = ()
    """Players who may be put on the team or named by the Assassin."""
    can_fail: bool = False
    """Whether a fail card is allowed on this mission."""


@dataclass(frozen=True, slots=True)
class PlayerView:
    game_id: str
    version: int
    phase: Phase
    ruleset_id: str
    you_id: str
    host_id: str
    leader_id: str | None
    players: tuple[PlayerInfo, ...]
    missions: tuple[MissionInfo, ...]
    current_mission_number: int | None
    proposal_number: int | None
    max_rejected_proposals: int
    missions_to_win: int
    proposed_team: tuple[str, ...]
    team_voted: tuple[str, ...]
    """Who has voted on the open proposal. The votes stay hidden until all are in."""
    your_team_vote: bool | None
    last_team_vote: TeamVoteRecord | None
    mission_played: tuple[str, ...]
    """Team members who have played a card. The cards themselves are never shown."""
    your_mission_card: bool | None
    assassin_id: str | None
    assassination_target_id: str | None
    winner: Alignment | None
    win_reason: WinReason | None
    legal_actions: tuple[LegalAction, ...]


_PLAY_PHASES = (Phase.TEAM_PROPOSAL, Phase.TEAM_VOTE, Phase.MISSION_VOTE)


def build_player_view(state: GameState, player_id: str) -> PlayerView:
    viewer = _require_player(state, player_id)
    started = state.phase is not Phase.LOBBY
    finished = state.phase is Phase.FINISHED
    in_play = state.phase in _PLAY_PHASES

    return PlayerView(
        game_id=state.game_id,
        version=state.version,
        phase=state.phase,
        ruleset_id=state.ruleset.id,
        you_id=viewer.id,
        host_id=state.host_id,
        leader_id=state.leader_id,
        players=tuple(_player_info(viewer, player, finished) for player in state.players),
        missions=tuple(
            MissionInfo(
                number=mission.number,
                team_size=mission.team_size,
                fails_required=mission.fails_required,
                team=mission.team,
                outcome=mission.outcome,
                fail_votes=mission.fail_votes,
            )
            for mission in state.missions
        ),
        current_mission_number=state.current_mission.number if started else None,
        proposal_number=state.proposal_number if in_play else None,
        max_rejected_proposals=state.ruleset.max_rejected_proposals,
        missions_to_win=state.ruleset.missions_to_win,
        proposed_team=state.proposed_team,
        team_voted=tuple(vote.player_id for vote in state.team_votes),
        your_team_vote=next(
            (vote.approve for vote in state.team_votes if vote.player_id == viewer.id), None
        ),
        last_team_vote=state.last_team_vote,
        mission_played=tuple(vote.player_id for vote in state.mission_votes),
        your_mission_card=next(
            (vote.success for vote in state.mission_votes if vote.player_id == viewer.id), None
        ),
        assassin_id=_public_assassin_id(state),
        assassination_target_id=state.assassination_target_id,
        winner=state.winner,
        win_reason=state.win_reason,
        legal_actions=legal_actions(state, viewer.id),
    )


def legal_actions(state: GameState, player_id: str) -> tuple[LegalAction, ...]:
    """The actions `apply_action` would accept from this player right now."""
    player = _require_player(state, player_id)

    match state.phase:
        case Phase.LOBBY:
            ruleset = state.ruleset
            enough = ruleset.min_players <= len(state.players) <= ruleset.max_players
            if player.id == state.host_id and enough:
                return (LegalAction(type="start_game"),)
        case Phase.TEAM_PROPOSAL:
            if player.id == state.leader_id:
                return (
                    LegalAction(
                        type="propose_team",
                        team_size=state.current_mission.team_size,
                        targets=state.player_ids,
                    ),
                )
        case Phase.TEAM_VOTE:
            if all(vote.player_id != player.id for vote in state.team_votes):
                return (LegalAction(type="vote_team"),)
        case Phase.MISSION_VOTE:
            on_team = player.id in state.current_mission.team
            played = any(vote.player_id == player.id for vote in state.mission_votes)
            if on_team and not played:
                is_evil = _role(player).alignment is Alignment.EVIL
                return (LegalAction(type="vote_mission", can_fail=is_evil),)
        case Phase.ASSASSINATION:
            if player.role is Role.ASSASSIN:
                others = tuple(pid for pid in state.player_ids if pid != player.id)
                return (LegalAction(type="assassinate", targets=others),)
        case Phase.FINISHED:
            pass
    return ()


def _require_player(state: GameState, player_id: str) -> PlayerState:
    player = state.find_player(player_id)
    if player is None:
        raise RuleViolation(ErrorCode.UNKNOWN_PLAYER, f"Player '{player_id}' is not in this game.")
    return player


def _role(player: PlayerState) -> Role:
    assert player.role is not None, "roles are assigned when the game starts"
    return player.role


def _player_info(viewer: PlayerState, player: PlayerState, finished: bool) -> PlayerInfo:
    if player.role is None or viewer.role is None:
        return PlayerInfo(id=player.id, seat=player.seat, role=None, alignment=None, seen_as=None)

    if finished or player.id == viewer.id:
        return PlayerInfo(
            id=player.id,
            seat=player.seat,
            role=player.role,
            alignment=player.role.alignment,
            seen_as=None,
        )

    return PlayerInfo(
        id=player.id,
        seat=player.seat,
        role=None,
        alignment=None,
        seen_as=_seen_as(viewer.role, player.role),
    )


def _seen_as(viewer: Role, target: Role) -> Knowledge | None:
    """The night-phase knowledge from the rulebook."""
    target_is_evil = target.alignment is Alignment.EVIL

    if viewer is Role.MERLIN:
        # Merlin sees evil, except Mordred.
        return Knowledge.EVIL if target_is_evil and target is not Role.MORDRED else None
    if viewer is Role.PERCIVAL:
        # Percival sees Merlin and Morgana but cannot tell them apart.
        return Knowledge.MERLIN_OR_MORGANA if target in (Role.MERLIN, Role.MORGANA) else None
    if viewer.alignment is Alignment.EVIL and viewer is not Role.OBERON:
        # Evil players know each other, except Oberon, who is unknown to them.
        return Knowledge.EVIL if target_is_evil and target is not Role.OBERON else None
    return None


def _public_assassin_id(state: GameState) -> str | None:
    """The Assassin steps forward once the assassination begins."""
    if state.phase not in (Phase.ASSASSINATION, Phase.FINISHED):
        return None
    return next((player.id for player in state.players if player.role is Role.ASSASSIN), None)
