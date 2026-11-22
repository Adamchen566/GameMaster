"""The contract between the game and a model-driven player.

    PlayerView ──build_observation──> AgentObservation ──(model)──> AgentDecision
                                                                        │
    Action  <──────────────to_action(view, decision)────────────────────┘

Two rules make a model no more powerful than a human in the same seat:

1. An observation is built only from that seat's `PlayerView` and the public
   log, so there is nothing secret in it to leak.
2. A decision is only a proposal. `to_action` accepts it if, and only if, it is
   one of the view's legal actions with player ids taken from that action's
   targets. Everything else raises `InvalidDecision`; the engine then checks
   the action again like any other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.game.actions import Action, Assassinate, ProposeTeam, VoteMission, VoteTeam
from app.game.public_log import PublicEntry
from app.game.views import LegalAction, PlayerView

HISTORY_LIMIT = 30
"""Public log entries shown to the model: the most recent ones, a fixed number."""
NOTE_LIMIT = 400
"""Characters of private notes a player may carry from one turn to the next."""
NAME_LIMIT = 20

ACTION_TYPES = ("propose_team", "vote_team", "vote_mission", "assassinate")


class InvalidDecision(Exception):
    """The model's answer cannot be turned into a legal action.

    The message is safe to send back to the model: it only repeats what the
    observation already said.
    """


@dataclass(frozen=True, slots=True)
class AgentObservation:
    data: Mapping[str, Any]
    """JSON-compatible; exactly what is sent to the model."""


@dataclass(frozen=True, slots=True)
class AgentDecision:
    action: str
    team: tuple[str, ...]
    approve: bool
    success: bool
    target_id: str
    note: str
    """The player's private reasoning for its own later turns. Never shown to anyone."""


# Every field is required so the schema stays within what structured outputs
# guarantee; fields that do not apply to the chosen action are ignored.
DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTION_TYPES)},
        "team": {"type": "array", "items": {"type": "string"}},
        "approve": {"type": "boolean"},
        "success": {"type": "boolean"},
        "target_id": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["action", "team", "approve", "success", "target_id", "note"],
    "additionalProperties": False,
}


def clean_name(name: str) -> str:
    """Names are typed by people. Keep them printable, single-line and short."""
    single_line = " ".join(name.split())
    return "".join(character for character in single_line if character.isprintable())[:NAME_LIMIT]


def _legal_json(legal: LegalAction) -> dict[str, Any]:
    return {
        "type": legal.type,
        "team_size": legal.team_size,
        "targets": list(legal.targets),
        "can_fail": legal.can_fail,
    }


def build_observation(
    view: PlayerView,
    *,
    names: Mapping[str, str],
    history: Sequence[PublicEntry],
    note: str = "",
) -> AgentObservation:
    """Describe the game to the player in `view.you_id`'s seat, and nothing more."""
    you = next(player for player in view.players if player.id == view.you_id)
    return AgentObservation(
        data={
            "you": {
                "id": you.id,
                "role": you.role.value if you.role else None,
                "alignment": you.alignment.value if you.alignment else None,
            },
            "phase": view.phase.value,
            "players": [
                {
                    "id": player.id,
                    "seat": player.seat,
                    "name": clean_name(names.get(player.id, player.id)),
                    "is_leader": player.id == view.leader_id,
                    "known_to_you_as": player.seen_as.value if player.seen_as else None,
                }
                for player in view.players
            ],
            "missions": [
                {
                    "number": mission.number,
                    "team_size": mission.team_size,
                    "fails_required": mission.fails_required,
                    "team": list(mission.team),
                    "outcome": mission.outcome.value if mission.outcome else None,
                    "fail_votes": mission.fail_votes,
                }
                for mission in view.missions
            ],
            "current_mission": view.current_mission_number,
            "proposal_number": view.proposal_number,
            "max_rejected_proposals": view.max_rejected_proposals,
            "missions_to_win": view.missions_to_win,
            "proposed_team": list(view.proposed_team),
            "legal_actions": [_legal_json(legal) for legal in view.legal_actions],
            "public_history": [entry.to_json() for entry in history[-HISTORY_LIMIT:]],
            "your_notes": note[:NOTE_LIMIT],
        }
    )


def decision_from_data(data: object) -> AgentDecision:
    """Check the shape of a model's answer. Types are strict: no coercion."""
    if not isinstance(data, Mapping):
        raise InvalidDecision("The answer must be a JSON object.")

    def field(name: str, expected: type) -> Any:
        value = data.get(name)
        # bool is a subclass of int; never accept one for the other.
        if type(value) is not expected:
            raise InvalidDecision(f"Field '{name}' must be a {expected.__name__}.")
        return value

    team = field("team", list)
    if not all(type(member) is str for member in team):
        raise InvalidDecision("Field 'team' must be a list of player ids.")

    return AgentDecision(
        action=field("action", str),
        team=tuple(team),
        approve=field("approve", bool),
        success=field("success", bool),
        target_id=field("target_id", str),
        note=field("note", str)[:NOTE_LIMIT],
    )


def to_action(view: PlayerView, decision: AgentDecision) -> Action:
    """Turn a decision into an action, or refuse it. Ids must come from `legal_actions`."""
    legal = next((item for item in view.legal_actions if item.type == decision.action), None)
    if legal is None:
        allowed = ", ".join(item.type for item in view.legal_actions) or "nothing"
        raise InvalidDecision(
            f"Action '{decision.action}' is not available. You may only do: {allowed}."
        )

    you, version = view.you_id, view.version
    match legal.type:
        case "propose_team":
            team = decision.team
            if len(team) != legal.team_size:
                raise InvalidDecision(f"The team must have exactly {legal.team_size} players.")
            if len(set(team)) != len(team):
                raise InvalidDecision("The team must not name a player twice.")
            unknown = [member for member in team if member not in legal.targets]
            if unknown:
                raise InvalidDecision(
                    "The team may only contain ids from legal_actions[].targets; "
                    f"not allowed: {', '.join(sorted(unknown))}."
                )
            return ProposeTeam(player_id=you, team=team, expected_version=version)
        case "vote_team":
            return VoteTeam(player_id=you, approve=decision.approve, expected_version=version)
        case "vote_mission":
            if not decision.success and not legal.can_fail:
                raise InvalidDecision("You may not play a fail card on this mission.")
            return VoteMission(player_id=you, success=decision.success, expected_version=version)
        case "assassinate":
            if decision.target_id not in legal.targets:
                raise InvalidDecision("target_id must be one of legal_actions[].targets.")
            return Assassinate(
                player_id=you, target_id=decision.target_id, expected_version=version
            )
        case other:
            # start_game is the host's call and the host is a human.
            raise InvalidDecision(f"A model may not perform '{other}'.")
