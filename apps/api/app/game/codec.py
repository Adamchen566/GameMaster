"""Turn events into plain JSON-compatible data and back.

The event log is stored as one JSON object per event. Decoding is written out
per event type on purpose: a stored event is a long-lived contract, so a field
that is renamed or retyped must fail here, loudly, instead of being guessed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import fields
from enum import Enum
from typing import Any

from app.game.events import (
    AssassinationAttempted,
    AssassinationStarted,
    GameEvent,
    GameFinished,
    GameStarted,
    MissionCompleted,
    MissionStarted,
    MissionVoteCast,
    PlayerSpoke,
    TeamApproved,
    TeamProposed,
    TeamRejected,
    TeamVoteCast,
)
from app.game.rulesets import Alignment, Role
from app.game.state import MissionOutcome, WinReason

Payload = Mapping[str, Any]


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def encode_event(event: GameEvent) -> tuple[str, dict[str, object]]:
    """Return the event's type name and its fields as JSON-compatible data."""
    payload = {
        field.name: _plain(getattr(event, field.name))
        for field in fields(event)
        if field.name != "type"
    }
    return event.type, payload


def _ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"Expected a list of player ids, got {type(value).__name__}.")
    return tuple(str(item) for item in value)


def _game_started(p: Payload) -> GameStarted:
    return GameStarted(
        seed=int(p["seed"]),
        roles=tuple((str(player_id), Role(role)) for player_id, role in p["roles"]),
    )


def _mission_started(p: Payload) -> MissionStarted:
    return MissionStarted(mission_number=int(p["mission_number"]), leader_id=str(p["leader_id"]))


def _team_proposed(p: Payload) -> TeamProposed:
    return TeamProposed(
        mission_number=int(p["mission_number"]),
        proposal_number=int(p["proposal_number"]),
        leader_id=str(p["leader_id"]),
        team=_ids(p["team"]),
    )


def _player_spoke(p: Payload) -> PlayerSpoke:
    return PlayerSpoke(
        mission_number=int(p["mission_number"]),
        proposal_number=int(p["proposal_number"]),
        player_id=str(p["player_id"]),
        text=str(p["text"]),
        suspects=_ids(p["suspects"]),
    )


def _team_vote_cast(p: Payload) -> TeamVoteCast:
    return TeamVoteCast(player_id=str(p["player_id"]), approve=bool(p["approve"]))


def _team_approved(p: Payload) -> TeamApproved:
    return TeamApproved(
        mission_number=int(p["mission_number"]),
        proposal_number=int(p["proposal_number"]),
        approvals=_ids(p["approvals"]),
        rejections=_ids(p["rejections"]),
    )


def _team_rejected(p: Payload) -> TeamRejected:
    return TeamRejected(
        mission_number=int(p["mission_number"]),
        proposal_number=int(p["proposal_number"]),
        approvals=_ids(p["approvals"]),
        rejections=_ids(p["rejections"]),
        next_leader_id=str(p["next_leader_id"]),
    )


def _mission_vote_cast(p: Payload) -> MissionVoteCast:
    return MissionVoteCast(player_id=str(p["player_id"]), success=bool(p["success"]))


def _mission_completed(p: Payload) -> MissionCompleted:
    return MissionCompleted(
        mission_number=int(p["mission_number"]),
        fail_votes=int(p["fail_votes"]),
        outcome=MissionOutcome(p["outcome"]),
    )


def _assassination_started(p: Payload) -> AssassinationStarted:
    return AssassinationStarted(assassin_id=str(p["assassin_id"]))


def _assassination_attempted(p: Payload) -> AssassinationAttempted:
    return AssassinationAttempted(assassin_id=str(p["assassin_id"]), target_id=str(p["target_id"]))


def _game_finished(p: Payload) -> GameFinished:
    return GameFinished(winner=Alignment(p["winner"]), reason=WinReason(p["reason"]))


_DECODERS: dict[str, Callable[[Payload], GameEvent]] = {
    "game_started": _game_started,
    "mission_started": _mission_started,
    "team_proposed": _team_proposed,
    "player_spoke": _player_spoke,
    "team_vote_cast": _team_vote_cast,
    "team_approved": _team_approved,
    "team_rejected": _team_rejected,
    "mission_vote_cast": _mission_vote_cast,
    "mission_completed": _mission_completed,
    "assassination_started": _assassination_started,
    "assassination_attempted": _assassination_attempted,
    "game_finished": _game_finished,
}

EVENT_TYPES = frozenset(_DECODERS)


def decode_event(event_type: str, payload: Payload) -> GameEvent:
    """Rebuild an event from what `encode_event` produced."""
    decoder = _DECODERS.get(event_type)
    if decoder is None:
        raise ValueError(f"Unknown event type '{event_type}'.")
    return decoder(payload)
