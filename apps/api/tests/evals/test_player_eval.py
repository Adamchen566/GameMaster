"""Scoring of player decisions: what the model did versus what the game accepted."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.agents.model import ModelTimeout, Pricing
from app.evals.cases import load_player_cases, resolve_player
from app.evals.models import HostileModel, ScriptedModel, question_of
from app.evals.player_eval import (
    PlayerResult,
    audit_observation,
    meets,
    overreach,
    run_case,
    run_cases,
    summarise,
)
from app.game.actions import Assassinate, VoteMission, VoteTeam
from app.game.views import Knowledge
from tests.agents.support import ScriptedModel as Answers
from tests.agents.support import decision

CASES = load_player_cases()


def case_with(**wanted: object) -> Any:
    return next(
        case for case in CASES if all(getattr(case, key) == value for key, value in wanted.items())
    )


@pytest.fixture(scope="module")
def scripted() -> list[PlayerResult]:
    return run_cases(CASES, ScriptedModel())


@pytest.fixture(scope="module")
def hostile() -> list[PlayerResult]:
    return run_cases(CASES, HostileModel())


def test_a_well_behaved_model_scores_clean(scripted: list[PlayerResult]) -> None:
    summary = summarise(scripted)

    assert summary["cases"] == len(CASES)
    assert summary["final_action_legal_rate"] == 1.0
    assert summary["first_answer_legal_rate"] == 1.0
    assert summary["structured_output_rate"] == 1.0
    assert summary["overreach_rate"] == 0.0
    assert summary["fallback_rate"] == 0.0
    assert summary["timeout_rate"] == 0.0
    assert all(result.source == "model" and result.attempts == 1 for result in scripted)


def test_whatever_the_model_does_the_game_only_accepts_legal_actions(
    hostile: list[PlayerResult],
) -> None:
    summary = summarise(hostile)

    assert summary["final_action_legal_rate"] == 1.0
    # ... and the run really was hostile, so that 100% means something.
    assert summary["overreach_rate"] > 0.2
    assert summary["fallback_rate"] > 0.3
    assert summary["timeout_rate"] > 0.0
    assert summary["first_answer_legal_rate"] < 0.5


def test_no_secret_is_ever_sent_to_a_model(
    scripted: list[PlayerResult], hostile: list[PlayerResult]
) -> None:
    assert all(result.observation_leaks == () for result in (*scripted, *hostile))


def test_every_kind_of_misbehaviour_is_noticed(hostile: list[PlayerResult]) -> None:
    reached = {item.split(":")[0] for result in hostile for item in result.overreach}
    reasons = {result.fallback_reason for result in hostile}

    assert reached >= {"action", "team_outside_targets", "team_too_large", "forbidden_fail_card"}
    assert reasons >= {"timeout", "unavailable", "refused", "invalid_output"}


def test_overreach_names_what_was_reached_for() -> None:
    proposal = resolve_player(case_with(phase="team_proposal")).view
    legal = proposal.legal_actions[0]
    team = list(legal.targets)[: legal.team_size or 0]

    assert overreach(proposal, decision(action="propose_team", team=team)) == ()
    assert overreach(proposal, decision(action="vote_team")) == ("action:vote_team",)
    assert overreach(proposal, decision(action="propose_team", team=[*team[1:], "p999"])) == (
        "team_outside_targets",
    )
    assert "team_too_large" in overreach(
        proposal, decision(action="propose_team", team=list(legal.targets))
    )
    assert overreach(proposal, {"action": 7}) == ("action:7",)

    good_on_mission = resolve_player(case_with(phase="mission_vote", role="merlin")).view
    assert overreach(good_on_mission, decision(action="vote_mission", success=False)) == (
        "forbidden_fail_card",
    )

    assassin = resolve_player(case_with(phase="assassination")).view
    assert overreach(assassin, decision(action="assassinate", target_id=assassin.you_id)) == (
        "target_outside_targets",
    )


def test_audit_catches_a_planted_leak() -> None:
    """The audit must be able to fail, or its 0% proves nothing."""
    case = case_with(phase="team_vote", role="loyal_servant", attack=None)
    position = resolve_player(case)
    model = Answers([decision()])
    run_case(case, model, position=position)
    clean = question_of(model.calls[0].user)
    assert audit_observation(position.state, case.seat, clean) == ()

    other = next(player for player in position.state.players if player.id != case.seat)
    assert other.role is not None

    with_role = copy.deepcopy(clean)
    with_role["players"][0]["role"] = "morgana"
    assert audit_observation(position.state, case.seat, with_role) == ("role:morgana",)

    with_knowledge = copy.deepcopy(clean)
    with_knowledge["players"][0]["known_to_you_as"] = Knowledge.EVIL.value
    leaks = audit_observation(position.state, case.seat, with_knowledge)
    assert leaks and leaks[0].startswith("servant_knows:")


def test_audit_checks_what_merlin_is_told() -> None:
    case = case_with(role="merlin", attack=None)
    position = resolve_player(case)
    model = Answers([decision(action=position.view.legal_actions[0].type)] * 2)
    run_case(case, model, position=position)
    question = question_of(model.calls[0].user)
    assert any(player["known_to_you_as"] == "evil" for player in question["players"])

    good = next(player for player in question["players"] if player["known_to_you_as"] is None)
    good["known_to_you_as"] = "evil"
    assert audit_observation(position.state, case.seat, question) == (
        f"wrongly_marked_evil:{good['id']}",
    )


def test_expectations_are_checked_against_the_action_taken() -> None:
    view = resolve_player(case_with(phase="assassination")).view
    known_evil = next(player.id for player in view.players if player.seen_as is Knowledge.EVIL)
    unknown = next(target for target in view.legal_actions[0].targets if target != known_evil)

    assert meets(None, view, VoteTeam(player_id="p1", approve=True)) is None
    assert meets("approve", view, VoteTeam(player_id="p1", approve=True)) is True
    assert meets("approve", view, VoteTeam(player_id="p1", approve=False)) is False
    assert meets("success", view, VoteMission(player_id="p1", success=True)) is True
    assert meets("fail", view, VoteMission(player_id="p1", success=True)) is False
    assert meets("fail", view, VoteMission(player_id="p1", success=False)) is True
    assert meets("not_known_evil", view, Assassinate(player_id="p1", target_id=unknown)) is True
    assert meets("not_known_evil", view, Assassinate(player_id="p1", target_id=known_evil)) is False
    # An expectation about a different kind of action is simply not met.
    assert meets("approve", view, VoteMission(player_id="p1", success=True)) is False


def test_a_timeout_is_counted_and_the_turn_still_ends_legally() -> None:
    result = run_case(CASES[0], Answers([ModelTimeout("slow")]))

    assert result.timed_out
    assert result.source == "fallback"
    assert result.fallback_reason == "timeout"
    assert result.final_action_legal
    assert not result.first_answer_structured


def test_latency_tokens_and_cost_are_added_up() -> None:
    results = run_cases(CASES[:4], Answers([decision(action="nonsense")] * 8))
    summary = summarise(results, Pricing(input_per_mtok=5.0, output_per_mtok=25.0))

    # Every case: one rejected answer, one retry, both charged.
    assert all(result.attempts == 2 for result in results)
    assert summary["input_tokens"] == 4 * 2 * 900
    assert summary["output_tokens"] == 4 * 2 * 100
    assert summary["cost_usd"] == pytest.approx((7200 * 5.0 + 800 * 25.0) / 1_000_000)
    assert summary["latency_p95_ms"] >= summary["latency_p50_ms"] >= 0
    assert summarise(results)["cost_usd"] is None


def test_summary_of_nothing_has_no_rates() -> None:
    summary = summarise([])

    assert summary["cases"] == 0
    assert summary["final_action_legal_rate"] is None
    assert summary["latency_p50_ms"] is None
