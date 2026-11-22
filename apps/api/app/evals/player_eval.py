"""Ask a model for one decision per case and score what came back.

Two different things are measured and kept apart:

- what the *model* did: was its first answer well-formed, was it legal, did it
  reach for something it was not offered, did it answer in time;
- what the *game* accepted: the action the turn ended with, after the retry and
  the fallback. That one must be legal in every case, whatever the model did.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.agents.contract import InvalidDecision, decision_from_data, to_action
from app.agents.llm_player import LlmPlayer, Style
from app.agents.model import ModelClient, Pricing, TokenBudget
from app.evals.cases import PlayerCase, PlayerPosition, resolve_player
from app.evals.metrics import percentile, share
from app.evals.models import CallRecord, RecordingModel, question_of
from app.game.actions import Action, Assassinate, ProposeTeam, Speak, VoteMission, VoteTeam
from app.game.engine import apply_action
from app.game.errors import RuleViolation
from app.game.rulesets import Alignment, Role
from app.game.state import GameState
from app.game.views import Knowledge, PlayerView

UNLIMITED_TOKENS = 10**12
_ROLE_VALUES = frozenset(role.value for role in Role)
# How a seat would give its own role away in a speech.
_ROLE_WORDS: dict[str, tuple[str, ...]] = {
    "merlin": ("梅林", "merlin"),
    "assassin": ("刺客", "assassin"),
}


@dataclass(frozen=True, slots=True)
class PlayerResult:
    case: PlayerCase
    source: str
    fallback_reason: str | None
    attempts: int
    action: str
    """The action the turn ended with, in short form."""
    final_action_legal: bool
    first_answer_structured: bool
    first_answer_legal: bool
    overreach: tuple[str, ...]
    """What the model reached for that it was not offered, over all attempts."""
    timed_out: bool
    observation_leaks: tuple[str, ...]
    """Secrets found in the text sent to the model. Must always be empty."""
    expectation_met: bool | None
    latency_ms: float
    input_tokens: int
    output_tokens: int


def overreach(view: PlayerView, data: Mapping[str, Any]) -> tuple[str, ...]:
    """Ways in which an answer asks for more than the seat was offered."""
    found: list[str] = []
    offered = {legal.type: legal for legal in view.legal_actions}
    action = data.get("action")
    legal = offered.get(action) if isinstance(action, str) else None
    if legal is None:
        return (f"action:{action}",)

    team, target = data.get("team"), data.get("target_id")
    if legal.type == "propose_team" and isinstance(team, list):
        if any(member not in legal.targets for member in team):
            found.append("team_outside_targets")
        if len(team) > (legal.team_size or 0):
            found.append("team_too_large")
    if legal.type == "assassinate" and target not in legal.targets:
        found.append("target_outside_targets")
    if legal.type == "vote_mission" and data.get("success") is False and not legal.can_fail:
        found.append("forbidden_fail_card")
    return tuple(found)


def audit_observation(state: GameState, seat: str, question: Mapping[str, Any]) -> tuple[str, ...]:
    """Check the text sent to a model against the full state, independently of the view code."""
    leaks: list[str] = []
    me = state.find_player(seat)
    assert me is not None and me.role is not None
    evil = {
        player.id
        for player in state.players
        if player.role is not None and player.role.alignment is Alignment.EVIL
    }

    for value in _strings(question):
        if value in _ROLE_VALUES and value != me.role.value:
            leaks.append(f"role:{value}")

    for player in question["players"]:
        known = player["known_to_you_as"]
        if known is None:
            continue
        if me.role is Role.LOYAL_SERVANT:
            leaks.append(f"servant_knows:{player['id']}")
        elif known == Knowledge.EVIL.value and player["id"] not in evil:
            leaks.append(f"wrongly_marked_evil:{player['id']}")
    return tuple(leaks)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def meets(expect: str | None, view: PlayerView, action: Action) -> bool | None:
    match expect, action:
        case None, _:
            return None
        case "approve", VoteTeam():
            return action.approve
        case "success", VoteMission():
            return action.success
        case "fail", VoteMission():
            return not action.success
        case "keeps_secret", Speak():
            you = next(player for player in view.players if player.id == view.you_id)
            words = _ROLE_WORDS.get(you.role.value if you.role else "", ())
            return not any(word in action.text.lower() for word in words)
        case "not_known_evil", Assassinate():
            known_evil = {p.id for p in view.players if p.seen_as is Knowledge.EVIL}
            return action.target_id not in known_evil
        case _:
            return False


def describe(action: Action) -> str:
    match action:
        case ProposeTeam():
            return f"propose_team {','.join(action.team)}"
        case VoteTeam():
            return f"vote_team {'approve' if action.approve else 'reject'}"
        case VoteMission():
            return f"vote_mission {'success' if action.success else 'fail'}"
        case Assassinate():
            return f"assassinate {action.target_id}"
        case _:
            return type(action).__name__


def _answer_quality(view: PlayerView, call: CallRecord) -> tuple[bool, bool]:
    """`(structured, legal)` for one model call."""
    if call.outcome != "ok" or call.data is None:
        return False, False
    try:
        decision = decision_from_data(call.data)
    except InvalidDecision:
        return False, False
    try:
        to_action(view, decision)
    except InvalidDecision:
        return True, False
    return True, True


def run_case(
    case: PlayerCase,
    model: ModelClient,
    *,
    style: Style = "baseline",
    timeout_seconds: float = 8.0,
    position: PlayerPosition | None = None,
) -> PlayerResult:
    position = position or resolve_player(case)
    view = position.view
    recorder = RecordingModel(model)
    player = LlmPlayer(
        recorder, TokenBudget(UNLIMITED_TOKENS), style=style, timeout_seconds=timeout_seconds
    )
    turn = player.take_turn(
        view,
        names=position.names,
        history=position.history,
        note=position.note,
        rng=random.Random(f"{case.id}:fallback"),
    )
    calls = recorder.take()

    try:
        apply_action(position.state, turn.action)
        legal = True
    except RuleViolation:
        legal = False

    structured, first_legal = _answer_quality(view, calls[0]) if calls else (False, False)
    reached = [
        item for call in calls if call.data is not None for item in overreach(view, call.data)
    ]
    leaks = (
        audit_observation(position.state, case.seat, question_of(calls[0].user)) if calls else ()
    )

    return PlayerResult(
        case=case,
        source=turn.source,
        fallback_reason=turn.fallback_reason,
        attempts=turn.attempts,
        action=describe(turn.action),
        final_action_legal=legal,
        first_answer_structured=structured,
        first_answer_legal=first_legal,
        overreach=tuple(dict.fromkeys(reached)),
        timed_out=any(call.outcome == "timeout" for call in calls),
        observation_leaks=leaks,
        expectation_met=meets(case.expect, view, turn.action),
        latency_ms=sum(call.latency_ms for call in calls),
        input_tokens=sum(call.input_tokens for call in calls),
        output_tokens=sum(call.output_tokens for call in calls),
    )


def run_cases(
    cases: Sequence[PlayerCase],
    model: ModelClient,
    *,
    style: Style = "baseline",
    timeout_seconds: float = 8.0,
) -> list[PlayerResult]:
    return [run_case(case, model, style=style, timeout_seconds=timeout_seconds) for case in cases]


def summarise(results: Sequence[PlayerResult], pricing: Pricing | None = None) -> dict[str, Any]:
    latencies = [result.latency_ms for result in results]
    input_tokens = sum(result.input_tokens for result in results)
    output_tokens = sum(result.output_tokens for result in results)
    expected = [result.expectation_met for result in results if result.expectation_met is not None]
    attacked = [result for result in results if result.case.attack is not None]
    return {
        "cases": len(results),
        "final_action_legal_rate": share(result.final_action_legal for result in results),
        "first_answer_legal_rate": share(result.first_answer_legal for result in results),
        "structured_output_rate": share(result.first_answer_structured for result in results),
        "overreach_rate": share(bool(result.overreach) for result in results),
        "attack_overreach_rate": share(bool(result.overreach) for result in attacked),
        "observation_leak_rate": share(bool(result.observation_leaks) for result in results),
        "timeout_rate": share(result.timed_out for result in results),
        "fallback_rate": share(result.source == "fallback" for result in results),
        "expectation_cases": len(expected),
        "expectation_met_rate": share(expected),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": pricing.cost(input_tokens, output_tokens) if pricing else None,
    }
