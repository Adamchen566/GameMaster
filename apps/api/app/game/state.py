"""Immutable game state.

This is the full, authoritative state and it contains secrets (roles, who
played which mission card). It must never be sent to a client or a model
directly; per-player views are built from it in a later slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.game.rulesets import Alignment, Role, RuleSet


class Phase(StrEnum):
    LOBBY = "lobby"
    TEAM_PROPOSAL = "team_proposal"
    DISCUSSION = "discussion"
    TEAM_VOTE = "team_vote"
    MISSION_VOTE = "mission_vote"
    ASSASSINATION = "assassination"
    FINISHED = "finished"


class MissionOutcome(StrEnum):
    SUCCESS = "success"
    FAIL = "fail"


class WinReason(StrEnum):
    MISSIONS_SUCCEEDED = "missions_succeeded"
    MERLIN_SURVIVED = "merlin_survived"
    MISSIONS_FAILED = "missions_failed"
    PROPOSALS_REJECTED = "proposals_rejected"
    MERLIN_ASSASSINATED = "merlin_assassinated"


@dataclass(frozen=True, slots=True)
class PlayerState:
    id: str
    seat: int
    """Position around the table; the leader passes to the next seat."""
    role: Role | None = None
    """None until the game starts."""


@dataclass(frozen=True, slots=True)
class MissionState:
    number: int
    """1-based."""
    team_size: int
    fails_required: int
    team: tuple[str, ...] = ()
    """Set once a proposal for this mission is approved."""
    fail_votes: int | None = None
    outcome: MissionOutcome | None = None


@dataclass(frozen=True, slots=True)
class Speech:
    """What one player said about the proposal on the table. Public."""

    player_id: str
    text: str
    suspects: tuple[str, ...] = ()
    """Players the speaker openly says they do not trust."""


@dataclass(frozen=True, slots=True)
class TeamVote:
    player_id: str
    approve: bool


@dataclass(frozen=True, slots=True)
class MissionVote:
    player_id: str
    success: bool


@dataclass(frozen=True, slots=True)
class TeamVoteRecord:
    """The revealed result of the most recent team vote."""

    mission_number: int
    proposal_number: int
    team: tuple[str, ...]
    approvals: tuple[str, ...]
    rejections: tuple[str, ...]
    approved: bool


@dataclass(frozen=True, slots=True)
class GameState:
    game_id: str
    ruleset: RuleSet
    host_id: str
    players: tuple[PlayerState, ...]
    """In seat order."""
    phase: Phase = Phase.LOBBY
    version: int = 0
    """Number of events applied so far."""
    missions: tuple[MissionState, ...] = ()
    mission_index: int = 0
    leader_id: str | None = None
    rejected_proposals: int = 0
    """Proposals rejected in a row for the current mission."""
    proposed_team: tuple[str, ...] = ()
    speeches: tuple[Speech, ...] = ()
    """What has been said about the latest proposal, in speaking order."""
    team_votes: tuple[TeamVote, ...] = ()
    mission_votes: tuple[MissionVote, ...] = ()
    last_team_vote: TeamVoteRecord | None = None
    assassination_target_id: str | None = None
    winner: Alignment | None = None
    win_reason: WinReason | None = None

    @property
    def player_ids(self) -> tuple[str, ...]:
        return tuple(player.id for player in self.players)

    def find_player(self, player_id: str) -> PlayerState | None:
        return next((player for player in self.players if player.id == player_id), None)

    @property
    def current_mission(self) -> MissionState:
        """The mission being proposed, voted on or played. Only valid once started."""
        return self.missions[self.mission_index]

    @property
    def proposal_number(self) -> int:
        """1-based number of the current proposal for the current mission."""
        return self.rejected_proposals + 1

    @property
    def speaking_order(self) -> tuple[str, ...]:
        """The leader speaks first, then everyone else clockwise from the leader."""
        ids = self.player_ids
        if self.leader_id is None:
            return ids
        start = ids.index(self.leader_id)
        return ids[start:] + ids[:start]

    @property
    def next_speaker_id(self) -> str | None:
        """Whose turn it is to speak, while the table is discussing a proposal."""
        if self.phase is not Phase.DISCUSSION:
            return None
        spoken = {speech.player_id for speech in self.speeches}
        return next((pid for pid in self.speaking_order if pid not in spoken), None)

    @property
    def successful_missions(self) -> int:
        return sum(mission.outcome is MissionOutcome.SUCCESS for mission in self.missions)

    @property
    def failed_missions(self) -> int:
        return sum(mission.outcome is MissionOutcome.FAIL for mission in self.missions)
