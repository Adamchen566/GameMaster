"""Whole games between policies."""

from __future__ import annotations

import pytest

from app.agents.llm_player import LlmPlayer
from app.agents.model import ModelClient, Pricing, TokenBudget
from app.evals.arena import Matchup, play_match, play_series, summarise
from app.evals.models import HostileModel, ScriptedModel

RANDOM = Matchup("random", "random")


def llm_with(model: ModelClient, max_tokens: int = 10**9) -> tuple[LlmPlayer, TokenBudget]:
    budget = TokenBudget(max_tokens)
    return LlmPlayer(model, budget), budget


@pytest.mark.parametrize("player_count", [5, 6, 7, 8, 9, 10])
def test_random_game_runs_to_a_winner(player_count: int) -> None:
    result = play_match(player_count, 3, RANDOM)

    assert result.winner in ("good", "evil")
    assert result.reason
    assert result.events > 10
    assert result.llm_turns == 0 and result.input_tokens == 0


def test_same_seed_same_game() -> None:
    assert play_match(7, 11, RANDOM) == play_match(7, 11, RANDOM)
    assert play_match(7, 11, RANDOM) != play_match(7, 12, RANDOM)


def test_model_side_plays_only_its_own_alignment() -> None:
    llm, budget = llm_with(ScriptedModel())

    good = play_match(5, 4, Matchup("llm", "random"), llm=llm, budget=budget)
    evil = play_match(5, 4, Matchup("random", "llm"), llm=llm, budget=budget)

    assert good.llm_turns > 0 and evil.llm_turns > 0
    assert good.llm_fallbacks == 0
    assert good.input_tokens > 0 and evil.input_tokens > 0


def test_a_misbehaving_model_still_finishes_the_game() -> None:
    llm, budget = llm_with(HostileModel())

    result = play_match(6, 2, Matchup("llm", "llm"), llm=llm, budget=budget)

    assert result.winner in ("good", "evil")
    assert 0 < result.llm_fallbacks <= result.llm_turns


def test_spent_budget_turns_model_seats_into_bots() -> None:
    llm, budget = llm_with(ScriptedModel(), max_tokens=2_000)

    result = play_match(5, 1, Matchup("llm", "llm"), llm=llm, budget=budget)

    assert result.llm_fallbacks > 0
    assert result.input_tokens + result.output_tokens < 6_000


def test_model_matchup_needs_a_model() -> None:
    with pytest.raises(ValueError, match="needs `llm` and `budget`"):
        play_match(5, 1, Matchup("llm", "random"))


def test_series_and_summary() -> None:
    llm, budget = llm_with(ScriptedModel())
    results = play_series([5, 6], 4, RANDOM)
    results += play_series([5], 2, Matchup("llm", "random"), llm=llm, budget=budget)

    summary = summarise(results, Pricing(input_per_mtok=5.0, output_per_mtok=25.0))
    rows = {(row["matchup"], row["player_count"]): row for row in summary["rows"]}

    assert set(rows) == {
        ("good=random, evil=random", 5),
        ("good=random, evil=random", 6),
        ("good=llm, evil=random", 5),
    }
    baseline = rows[("good=random, evil=random", 5)]
    assert baseline["games"] == 4
    assert baseline["good_win_rate"] == baseline["good_wins"] / 4
    assert sum(baseline["reasons"].values()) == 4
    assert baseline["llm_fallback_rate"] is None
    assert baseline["tokens_per_game"] == 0

    model = rows[("good=llm, evil=random", 5)]
    assert model["llm_fallback_rate"] == 0.0
    assert model["tokens_per_game"] > 0
    assert model["cost_per_game_usd"] > 0
    low, high = model["good_win_interval"]
    assert 0.0 <= low <= model["good_win_rate"] <= high <= 1.0


def test_every_matchup_is_played_on_the_same_seeds() -> None:
    """So a difference between matchups is the policy, not the luck of the deal."""
    llm, budget = llm_with(ScriptedModel())
    baseline = play_series([7], 3, RANDOM)
    model = play_series([7], 3, Matchup("llm", "random"), llm=llm, budget=budget)

    assert [r.seed for r in baseline] == [r.seed for r in model] == [1, 2, 3]
