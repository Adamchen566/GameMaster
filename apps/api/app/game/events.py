"""Facts that have happened in a game.

Events are the only thing that changes state (`engine.evolve`), so replaying a
game's events always rebuilds the same state. Several events contain secrets
(role assignments, individual mission cards); the event log is as private as
the state itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.game.rulesets import Alignment, Role
from app.game.state import MissionOutcome, WinReason


@dataclass(frozen=True, slots=True, kw_only=True)
class GameStarted:
    seed: int
    roles: tuple[tuple[str, Role], ...]
    """(player_id, role) pairs in seat order."""
    type: Literal["game_started"] = "game_started"


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionStarted:
    mission_number: int
    leader_id: str
    type: Literal["mission_started"] = "mission_started"


@dataclass(frozen=True, slots=True, kw_only=True)
class TeamProposed:
    mission_number: int
    proposal_number: int
    leader_id: str
    team: tuple[str, ...]
    type: Literal["team_proposed"] = "team_proposed"


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayerSpoke:
    mission_number: int
    proposal_number: int
    player_id: str
    text: str
    suspects: tuple[str, ...]
    type: Literal["player_spoke"] = "player_spoke"


@dataclass(frozen=True, slots=True, kw_only=True)
class TeamVoteCast:
    player_id: str
    approve: bool
    type: Literal["team_vote_cast"] = "team_vote_cast"


@dataclass(frozen=True, slots=True, kw_only=True)
class TeamApproved:
    mission_number: int
    proposal_number: int
    approvals: tuple[str, ...]
    rejections: tuple[str, ...]
    type: Literal["team_approved"] = "team_approved"


@dataclass(frozen=True, slots=True, kw_only=True)
class TeamRejected:
    mission_number: int
    proposal_number: int
    approvals: tuple[str, ...]
    rejections: tuple[str, ...]
    next_leader_id: str
    type: Literal["team_rejected"] = "team_rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionVoteCast:
    player_id: str
    success: bool
    type: Literal["mission_vote_cast"] = "mission_vote_cast"


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionCompleted:
    mission_number: int
    fail_votes: int
    outcome: MissionOutcome
    type: Literal["mission_completed"] = "mission_completed"


@dataclass(frozen=True, slots=True, kw_only=True)
class AssassinationStarted:
    assassin_id: str
    type: Literal["assassination_started"] = "assassination_started"


@dataclass(frozen=True, slots=True, kw_only=True)
class AssassinationAttempted:
    assassin_id: str
    target_id: str
    type: Literal["assassination_attempted"] = "assassination_attempted"


@dataclass(frozen=True, slots=True, kw_only=True)
class GameFinished:
    winner: Alignment
    reason: WinReason
    type: Literal["game_finished"] = "game_finished"


GameEvent = (
    GameStarted
    | MissionStarted
    | TeamProposed
    | PlayerSpoke
    | TeamVoteCast
    | TeamApproved
    | TeamRejected
    | MissionVoteCast
    | MissionCompleted
    | AssassinationStarted
    | AssassinationAttempted
    | GameFinished
)
