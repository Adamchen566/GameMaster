"""What everyone at the table saw happen.

The event log contains secrets (who was dealt which role, who played which
mission card). `public_log` keeps only what is announced out loud in a real
game. It is the single source for anything that narrates or remembers a game:
the AI game master and the memory of model-driven players read this, never the
events themselves.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.game.events import (
    AssassinationAttempted,
    AssassinationStarted,
    GameEvent,
    GameFinished,
    MissionCompleted,
    MissionStarted,
    PlayerSpoke,
    TeamApproved,
    TeamProposed,
    TeamRejected,
)


@dataclass(frozen=True, slots=True)
class PublicEntry:
    version: int
    """Version of the game after the event; unique within a game."""
    kind: str
    data: Mapping[str, object]

    def to_json(self) -> dict[str, object]:
        return {"version": self.version, "kind": self.kind, **self.data}


def _entry(version: int, event: GameEvent) -> PublicEntry | None:
    data: dict[str, object]
    match event:
        case MissionStarted():
            kind = "mission_started"
            data = {"mission": event.mission_number, "leader": event.leader_id}
        case TeamProposed():
            kind = "team_proposed"
            data = {
                "mission": event.mission_number,
                "proposal": event.proposal_number,
                "leader": event.leader_id,
                "team": list(event.team),
            }
        case PlayerSpoke():
            kind = "speech"
            data = {
                "mission": event.mission_number,
                "proposal": event.proposal_number,
                "player": event.player_id,
                "text": event.text,
                "suspects": list(event.suspects),
            }
        case TeamApproved() | TeamRejected():
            kind = "team_vote"
            data = {
                "mission": event.mission_number,
                "proposal": event.proposal_number,
                "approved": isinstance(event, TeamApproved),
                "approvals": list(event.approvals),
                "rejections": list(event.rejections),
            }
        case MissionCompleted():
            kind = "mission_result"
            data = {
                "mission": event.mission_number,
                "outcome": event.outcome.value,
                "fail_votes": event.fail_votes,
            }
        case AssassinationStarted():
            kind = "assassination_started"
            data = {"assassin": event.assassin_id}
        case AssassinationAttempted():
            kind = "assassination"
            data = {"assassin": event.assassin_id, "target": event.target_id}
        case GameFinished():
            kind = "game_finished"
            data = {"winner": event.winner.value, "reason": event.reason.value}
        case _:
            # GameStarted (the deal) and the individual vote and mission cards.
            return None
    return PublicEntry(version=version, kind=kind, data=MappingProxyType(data))


def public_log(events: Iterable[GameEvent], *, first_version: int = 1) -> tuple[PublicEntry, ...]:
    """Project events onto what was public. `first_version` is the version of the first event."""
    entries = (_entry(version, event) for version, event in enumerate(events, start=first_version))
    return tuple(entry for entry in entries if entry is not None)
