"""What the game needs from a language model, and how spending is limited.

`ModelClient` is deliberately tiny: one structured question, one structured
answer. The players and the game master depend on this interface only, so
tests run against scripted fakes and the provider can be swapped.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol


class ModelError(Exception):
    """Base class: the model did not produce a usable answer."""


class ModelTimeout(ModelError):
    """No answer within the time allowed."""


class ModelUnavailable(ModelError):
    """Network failure, rate limit, bad credentials or a server error."""


class ModelRefused(ModelError):
    """The provider declined to answer."""


class ModelBadOutput(ModelError):
    """An answer arrived but it is not the JSON object that was asked for."""


@dataclass(frozen=True, slots=True)
class ModelReply:
    data: Mapping[str, Any]
    input_tokens: int
    output_tokens: int


class ModelClient(Protocol):
    def complete(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        timeout_seconds: float,
    ) -> ModelReply:
        """Answer `user` with one JSON object matching `schema`, or raise a `ModelError`."""


@dataclass(frozen=True, slots=True)
class Pricing:
    """US dollars per million tokens."""

    input_per_mtok: float
    output_per_mtok: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / 1_000_000


@dataclass(frozen=True, slots=True)
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class TokenBudget:
    """A per-game ceiling on tokens, and optionally one for the whole server per day.

    Once either is reached, no more model calls are made. On a public server the
    daily ceiling is what bounds the bill: anyone can open as many games as they like.

    The check happens before a call and the charge after it, so one call can
    overshoot; the ceiling bounds the damage, it is not an exact meter.
    """

    def __init__(
        self,
        max_tokens_per_game: int,
        pricing: Pricing | None = None,
        *,
        max_tokens_per_day: int | None = None,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        if max_tokens_per_game < 0 or (max_tokens_per_day or 0) < 0:
            raise ValueError("The token budget cannot be negative.")
        self._max = max_tokens_per_game
        self._max_per_day = max_tokens_per_day
        self._today = today
        self._pricing = pricing
        self._usage: dict[str, Usage] = {}
        self._day: tuple[date, int] | None = None
        """(UTC day, tokens spent on it by every game together)."""
        self._lock = threading.Lock()

    def exhausted(self, game_id: str) -> bool:
        return self.usage(game_id).total_tokens >= self._max or self.day_exhausted()

    def day_exhausted(self) -> bool:
        if self._max_per_day is None:
            return False
        return self.spent_today() >= self._max_per_day

    def spent_today(self) -> int:
        with self._lock:
            if self._day is None or self._day[0] != self._today():
                return 0
            return self._day[1]

    def charge(self, game_id: str, reply: ModelReply) -> None:
        with self._lock:
            today = self._today()
            spent = self._day[1] if self._day is not None and self._day[0] == today else 0
            self._day = (today, spent + reply.input_tokens + reply.output_tokens)
            before = self._usage.get(game_id, Usage())
            self._usage[game_id] = Usage(
                calls=before.calls + 1,
                input_tokens=before.input_tokens + reply.input_tokens,
                output_tokens=before.output_tokens + reply.output_tokens,
            )

    def usage(self, game_id: str) -> Usage:
        with self._lock:
            return self._usage.get(game_id, Usage())

    def cost(self, game_id: str) -> float | None:
        """Estimated spend in US dollars, if prices were configured."""
        if self._pricing is None:
            return None
        usage = self.usage(game_id)
        return self._pricing.cost(usage.input_tokens, usage.output_tokens)
