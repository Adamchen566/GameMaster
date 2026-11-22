"""Scoring of narrations: what is checked automatically, and what is left to a person."""

from __future__ import annotations

import pytest

from app.agents.model import ModelTimeout, Pricing
from app.evals.cases import load_gm_cases
from app.evals.gm_eval import GmResult, run_case, run_cases, summarise
from app.evals.models import HostileModel, ScriptedModel
from app.evals.report import label_sheet
from tests.agents.support import ScriptedModel as Answers

CASES = load_gm_cases()


def colour(announcement: str) -> dict[str, str]:
    return {"tone": "tense", "announcement": announcement, "rule_hint": "none"}


@pytest.fixture(scope="module")
def scripted() -> list[GmResult]:
    return run_cases(CASES, ScriptedModel())


@pytest.fixture(scope="module")
def hostile() -> list[GmResult]:
    return run_cases(CASES, HostileModel())


def test_a_well_behaved_model_has_every_line_accepted(scripted: list[GmResult]) -> None:
    summary = summarise(scripted)

    assert summary["cases"] == len(CASES)
    assert summary["structured_output_rate"] == 1.0
    assert summary["template_fallback_rate"] == 0.0
    assert summary["lines_for_human_review"] == len(CASES)


def test_guarantees_hold_whatever_the_model_writes(
    scripted: list[GmResult], hostile: list[GmResult]
) -> None:
    for results in (scripted, hostile):
        summary = summarise(results)
        assert summary["facts_match_template_rate"] == 1.0
        assert summary["official_hint_rate"] == 1.0
        assert summary["within_limit_rate"] == 1.0
        assert summary["role_named_rate"] == 0.0
        assert summary["question_leak_rate"] == 0.0


def test_a_hostile_model_is_mostly_replaced_by_the_template(hostile: list[GmResult]) -> None:
    summary = summarise(hostile)

    assert summary["template_fallback_rate"] > 0.5
    assert summary["timeout_rate"] > 0.0
    assert all(
        result.announcement == result.facts for result in hostile if result.source == "template"
    )


def test_an_accusation_never_reaches_the_table(hostile: list[GmResult]) -> None:
    # Once the game is over the roles are public, so that event is not held to this.
    shown = [
        result.announcement
        for result in hostile
        if result.source == "model" and result.case.kind != "game_finished"
    ]

    assert shown, "some hostile lines are harmless and get through"
    assert not any("merlin" in line.lower() for line in shown)


def test_a_false_line_that_names_no_role_is_left_for_a_person(hostile: list[GmResult]) -> None:
    """The known limit of the automatic checks, and the reason the sheet exists."""
    lies = [result for result in hostile if "actually succeeded" in result.announcement]
    assert lies, "the hostile model contradicts the result in some cases"

    sheet = label_sheet(hostile)
    for result in lies:
        assert result.source == "model"
        assert result.case.id in sheet
    assert "consistent_with_facts (y/n)" in sheet.splitlines()[0]


def test_label_sheet_lists_model_lines_only(hostile: list[GmResult]) -> None:
    rows = label_sheet(hostile).strip().splitlines()[1:]
    written = [result for result in hostile if result.source == "model"]

    assert len(rows) == len(written)
    for result in hostile:
        if result.source == "template":
            assert not any(row.startswith(result.case.id + ",") for row in rows)


def test_a_timeout_is_counted_and_the_template_is_shown() -> None:
    result = run_case(CASES[0], Answers([ModelTimeout("slow")]))

    assert result.timed_out
    assert not result.model_answered
    assert result.source == "template"
    assert result.announcement == result.facts


def test_tokens_and_cost_are_added_up() -> None:
    results = run_cases(CASES[:3], Answers([colour("The hall is quiet.")] * 3))
    summary = summarise(results, Pricing(input_per_mtok=5.0, output_per_mtok=25.0))

    assert summary["input_tokens"] == 2700
    assert summary["output_tokens"] == 300
    assert summary["cost_usd"] == pytest.approx((2700 * 5.0 + 300 * 25.0) / 1_000_000)
    assert summarise([])["structured_output_rate"] is None
