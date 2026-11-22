"""Commands a player can submit.

Actions are requests, not facts: the engine validates each one and either
turns it into events or raises `RuleViolation`. The `type` field makes the
union easy to serialise and to discriminate at the API boundary.

Every action may carry `expected_version`, the state version the player was
looking at. If it is set and no longer current, the action is rejected instead
of being applied to a situation the player has not seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True, kw_only=True)
class StartGame:
    player_id: str
    seed: int
    """Drives the role shuffle and the first leader. The server chooses it, never a client."""
    expected_version: int | None = None
    type: Literal["start_game"] = "start_game"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProposeTeam:
    player_id: str
    team: tuple[str, ...]
    expected_version: int | None = None
    type: Literal["propose_team"] = "propose_team"


@dataclass(frozen=True, slots=True, kw_only=True)
class Speak:
    """Say something about the proposed team. An empty text is a pass."""

    player_id: str
    text: str = ""
    suspects: tuple[str, ...] = ()
    expected_version: int | None = None
    type: Literal["speak"] = "speak"


@dataclass(frozen=True, slots=True, kw_only=True)
class VoteTeam:
    player_id: str
    approve: bool
    expected_version: int | None = None
    type: Literal["vote_team"] = "vote_team"


@dataclass(frozen=True, slots=True, kw_only=True)
class VoteMission:
    player_id: str
    success: bool
    expected_version: int | None = None
    type: Literal["vote_mission"] = "vote_mission"


@dataclass(frozen=True, slots=True, kw_only=True)
class Assassinate:
    player_id: str
    target_id: str
    expected_version: int | None = None
    type: Literal["assassinate"] = "assassinate"


Action = StartGame | ProposeTeam | Speak | VoteTeam | VoteMission | Assassinate
