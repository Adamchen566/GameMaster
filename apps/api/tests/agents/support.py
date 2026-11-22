"""Scripted stand-ins for a language model."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.agents.model import ModelReply
from app.game.engine import replay
from app.game.public_log import PublicEntry, public_log
from app.game.simulate import play_random_game
from app.game.state import GameState, Phase
from app.game.views import build_player_view

Answer = Mapping[str, Any] | Exception | Callable[[str], Mapping[str, Any]]


@dataclass
class Call:
    system: str
    user: str
    schema: Mapping[str, Any]
    timeout_seconds: float


@dataclass
class ScriptedModel:
    """Returns the given answers in order; an exception is raised instead of returned."""

    answers: list[Answer]
    input_tokens: int = 900
    output_tokens: int = 100
    calls: list[Call] = field(default_factory=list)

    def complete(
        self, *, system: str, user: str, schema: Mapping[str, Any], timeout_seconds: float
    ) -> ModelReply:
        self.calls.append(Call(system, user, schema, timeout_seconds))
        if not self.answers:
            raise AssertionError("the model was called more often than the test expected")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        data = answer(user) if callable(answer) else answer
        return ModelReply(
            data=data, input_tokens=self.input_tokens, output_tokens=self.output_tokens
        )


def decision(**overrides: Any) -> dict[str, Any]:
    """A complete, well-formed answer; override the fields a test cares about."""
    return {
        "action": "vote_team",
        "team": [],
        "approve": True,
        "success": True,
        "target_id": "",
        "note": "",
        **overrides,
    }


NAMES = {f"p{number}": f"Player {number}" for number in range(1, 11)}


def position(
    phase: Phase, *, player_count: int = 7, seeds: range = range(200)
) -> tuple[GameState, tuple[PublicEntry, ...]]:
    """A real mid-game position in `phase`, with the public log that led to it."""
    for seed in seeds:
        game = play_random_game(player_count=player_count, seed=seed)
        for length in range(1, len(game.events) + 1):
            state = replay(game.initial, game.events[:length])
            # Skip the instants between events of one action, when nobody may act.
            waiting = any(
                build_player_view(state, player.id).legal_actions for player in state.players
            )
            if state.phase is phase and waiting:
                return state, public_log(game.events[:length])
    raise AssertionError(f"no game reached {phase}")
