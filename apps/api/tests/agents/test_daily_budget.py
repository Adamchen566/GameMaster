"""The server-wide daily ceiling: what bounds the bill when strangers can open games."""

from __future__ import annotations

from datetime import date

import pytest

from app.agents.model import ModelReply, TokenBudget
from app.api.deps import build_ai
from app.config import Settings


def reply(tokens: int) -> ModelReply:
    return ModelReply(data={}, input_tokens=tokens, output_tokens=0)


def test_every_game_together_stops_at_the_daily_ceiling() -> None:
    day = date(2026, 11, 22)
    budget = TokenBudget(1_000, max_tokens_per_day=1_500, today=lambda: day)

    budget.charge("game-a", reply(900))
    assert not budget.exhausted("game-b")

    budget.charge("game-b", reply(700))
    assert budget.exhausted("game-c"), "a fresh game is held back too"
    assert budget.spent_today() == 1_600


def test_the_daily_ceiling_starts_over_the_next_day() -> None:
    days = iter([date(2026, 11, 22)] * 3 + [date(2026, 11, 23)] * 3)
    budget = TokenBudget(10_000, max_tokens_per_day=100, today=lambda: next(days))

    budget.charge("game", reply(150))
    assert budget.day_exhausted()
    assert budget.spent_today() == 150

    assert not budget.day_exhausted()
    assert budget.spent_today() == 0


def test_without_a_daily_ceiling_only_the_game_ceiling_applies() -> None:
    budget = TokenBudget(100)
    budget.charge("a", reply(10_000))

    assert budget.exhausted("a")
    assert not budget.exhausted("b")
    assert not budget.day_exhausted()


def test_a_negative_daily_ceiling_is_refused() -> None:
    with pytest.raises(ValueError):
        TokenBudget(100, max_tokens_per_day=-1)


def test_the_server_reads_the_daily_ceiling_from_its_settings() -> None:
    from tests.agents.support import ScriptedModel

    ai = build_ai(Settings(llm_max_tokens_per_day=5), ScriptedModel([]))
    budget = ai["budget"]
    assert isinstance(budget, TokenBudget)
    budget.charge("g", reply(5))
    assert budget.exhausted("another")
