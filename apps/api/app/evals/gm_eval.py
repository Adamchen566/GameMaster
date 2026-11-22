"""Ask the game master to narrate each case and score what the server can check.

Checked here: the factual sentence is the template's, the rule hint is official
text, the model's line is within its limits, and how often the template had to
stand in. Not checked here: whether the model's own line is *true*. A line such
as "the mission actually succeeded" passes every automatic check, so each
model-written line goes on a sheet for a person to mark (`report.label_sheet`).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.agents.contract import clean_name
from app.agents.model import ModelClient, Pricing, TokenBudget
from app.evals.cases import GmCase, resolve_gm
from app.evals.metrics import percentile, share
from app.evals.models import RecordingModel
from app.game.rulesets import Role
from app.gm.narrator import ANNOUNCEMENT_LIMIT, Narrator
from app.gm.templates import (
    LANGUAGES,
    ROLES_PUBLIC_AFTER,
    RULE_HINTS,
    facts,
    hint_text,
    names_a_role,
)

UNLIMITED_TOKENS = 10**12
_ROLE_VALUES = frozenset(role.value for role in Role)
_OFFICIAL_HINTS = frozenset(
    hint_text(hint, language) for hint in RULE_HINTS for language in LANGUAGES
)


@dataclass(frozen=True, slots=True)
class GmResult:
    case: GmCase
    source: str
    tone: str
    facts: str
    announcement: str
    rule_hint: str
    facts_match_template: bool
    hint_is_official: bool
    within_limit: bool
    names_role: bool
    """The shown line names a role while the game is running. Must always be False."""
    question_leaks: tuple[str, ...]
    """Role names found in the text sent to the model. Must always be empty."""
    model_answered: bool
    timed_out: bool
    latency_ms: float
    input_tokens: int
    output_tokens: int


def run_case(case: GmCase, model: ModelClient, *, timeout_seconds: float = 3.0) -> GmResult:
    position = resolve_gm(case)
    recorder = RecordingModel(model)
    narrator = Narrator(recorder, TokenBudget(UNLIMITED_TOKENS), timeout_seconds=timeout_seconds)
    narration = narrator.narrate(position.game_id, position.entry, position.names, case.language)
    calls = recorder.take()

    safe_names = {player_id: clean_name(name) for player_id, name in position.names.items()}
    expected_facts = facts(position.entry, safe_names, case.language)
    leaks: list[str] = []
    for call in calls:
        question = json.loads(call.user)
        leaks.extend(
            f"role:{value}"
            for value in (*question["event"].values(), *question["names"].values())
            if isinstance(value, str) and value in _ROLE_VALUES
        )

    return GmResult(
        case=case,
        source=narration.source,
        tone=narration.tone,
        facts=narration.facts,
        announcement=narration.announcement,
        rule_hint=narration.rule_hint,
        facts_match_template=narration.facts == expected_facts,
        hint_is_official=narration.rule_hint in _OFFICIAL_HINTS,
        within_limit=0
        < len(narration.announcement)
        <= max(ANNOUNCEMENT_LIMIT, len(expected_facts)),
        names_role=(
            narration.source == "model"
            and case.kind != ROLES_PUBLIC_AFTER
            and names_a_role(narration.announcement)
        ),
        question_leaks=tuple(leaks),
        model_answered=any(call.outcome == "ok" for call in calls),
        timed_out=any(call.outcome == "timeout" for call in calls),
        latency_ms=sum(call.latency_ms for call in calls),
        input_tokens=sum(call.input_tokens for call in calls),
        output_tokens=sum(call.output_tokens for call in calls),
    )


def run_cases(
    cases: Sequence[GmCase], model: ModelClient, *, timeout_seconds: float = 3.0
) -> list[GmResult]:
    return [run_case(case, model, timeout_seconds=timeout_seconds) for case in cases]


def summarise(results: Sequence[GmResult], pricing: Pricing | None = None) -> dict[str, Any]:
    latencies = [result.latency_ms for result in results]
    input_tokens = sum(result.input_tokens for result in results)
    output_tokens = sum(result.output_tokens for result in results)
    return {
        "cases": len(results),
        "facts_match_template_rate": share(result.facts_match_template for result in results),
        "official_hint_rate": share(result.hint_is_official for result in results),
        "within_limit_rate": share(result.within_limit for result in results),
        "role_named_rate": share(result.names_role for result in results),
        "question_leak_rate": share(bool(result.question_leaks) for result in results),
        "structured_output_rate": share(result.source == "model" for result in results),
        "template_fallback_rate": share(result.source == "template" for result in results),
        "timeout_rate": share(result.timed_out for result in results),
        "lines_for_human_review": sum(result.source == "model" for result in results),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": pricing.cost(input_tokens, output_tokens) if pricing else None,
    }
