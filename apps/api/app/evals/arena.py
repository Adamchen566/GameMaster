"""Whole games between policies, to compare a model with the random legal bot.

A single decision can look clever and still lose games, so the comparison that
counts is the win rate over many seeded games: random against random as the
baseline, then the model on one side against the random bot on the other.
Every seat, whoever drives it, is given its own `PlayerView` and nothing else.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.agents import table_bot
from app.agents.llm_player import LlmPlayer
from app.agents.model import Pricing, TokenBudget
from app.agents.policy_fallback import choose_action
from app.evals.cases import default_names
from app.evals.metrics import rate, wilson_interval
from app.game.actions import StartGame
from app.game.engine import apply_action, new_game
from app.game.events import GameEvent
from app.game.public_log import public_log
from app.game.rulesets import OFFICIAL, Alignment
from app.game.state import Phase
from app.game.views import build_player_view

Policy = Literal["random", "bot", "llm"]


@dataclass(frozen=True, slots=True)
class Matchup:
    good: Policy
    evil: Policy

    @property
    def label(self) -> str:
        return f"good={self.good}, evil={self.evil}"


@dataclass(frozen=True, slots=True)
class MatchResult:
    player_count: int
    seed: int
    matchup: Matchup
    winner: str
    reason: str
    events: int
    llm_turns: int
    llm_fallbacks: int
    input_tokens: int
    output_tokens: int


def play_match(
    player_count: int,
    seed: int,
    matchup: Matchup,
    *,
    llm: LlmPlayer | None = None,
    budget: TokenBudget | None = None,
) -> MatchResult:
    """Play one game to the end. `llm` and `budget` are needed when a side is "llm"."""
    uses_llm = "llm" in (matchup.good, matchup.evil)
    if uses_llm and (llm is None or budget is None):
        raise ValueError("A matchup with a model side needs `llm` and `budget`.")

    player_ids = tuple(f"p{number}" for number in range(1, player_count + 1))
    game_id = f"arena-{player_count}-{seed}-{matchup.good}-{matchup.evil}"
    state = new_game(
        game_id=game_id, ruleset=OFFICIAL, player_ids=player_ids, host_id=player_ids[0]
    )
    events: list[GameEvent]
    state, events = apply_action(state, StartGame(player_id=player_ids[0], seed=seed))

    names = default_names(player_count, "en")
    notes: dict[str, str] = {}
    llm_turns = llm_fallbacks = 0

    while state.phase is not Phase.FINISHED:
        view = next(
            view
            for view in (build_player_view(state, player_id) for player_id in player_ids)
            if view.legal_actions
        )
        actor = state.find_player(view.you_id)
        assert actor is not None and actor.role is not None
        policy = matchup.good if actor.role.alignment is Alignment.GOOD else matchup.evil
        rng = random.Random(f"{seed}:{view.you_id}:{view.version}")

        if policy == "llm":
            assert llm is not None
            turn = llm.take_turn(
                view,
                names=names,
                history=public_log(events),
                note=notes.get(view.you_id, ""),
                rng=rng,
            )
            llm_turns += 1
            llm_fallbacks += turn.source == "fallback"
            if turn.note is not None:
                notes[view.you_id] = turn.note
            action = turn.action
        elif policy == "bot":
            action = table_bot.choose_action(
                view, rng, history=public_log(events), names=names, language="en", salt=str(seed)
            )
        else:
            action = choose_action(view, rng)

        state, new_events = apply_action(state, action)
        events.extend(new_events)

    assert state.winner is not None and state.win_reason is not None
    usage = budget.usage(game_id) if budget is not None else None
    return MatchResult(
        player_count=player_count,
        seed=seed,
        matchup=matchup,
        winner=state.winner.value,
        reason=state.win_reason.value,
        events=len(events),
        llm_turns=llm_turns,
        llm_fallbacks=llm_fallbacks,
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
    )


def play_series(
    player_counts: Sequence[int],
    games: int,
    matchup: Matchup,
    *,
    llm: LlmPlayer | None = None,
    budget: TokenBudget | None = None,
    first_seed: int = 1,
) -> list[MatchResult]:
    """`games` games per player count. The same seeds deal the same roles to every matchup."""
    return [
        play_match(player_count, seed, matchup, llm=llm, budget=budget)
        for player_count in player_counts
        for seed in range(first_seed, first_seed + games)
    ]


def summarise(results: Sequence[MatchResult], pricing: Pricing | None = None) -> dict[str, Any]:
    """Win rates per matchup and player count, with a 95% interval."""
    groups: dict[tuple[str, int], list[MatchResult]] = {}
    for result in results:
        groups.setdefault((result.matchup.label, result.player_count), []).append(result)

    rows = []
    for (label, player_count), group in sorted(groups.items()):
        good_wins = sum(result.winner == "good" for result in group)
        reasons: dict[str, int] = {}
        for result in group:
            reasons[result.reason] = reasons.get(result.reason, 0) + 1
        llm_turns = sum(result.llm_turns for result in group)
        input_tokens = sum(result.input_tokens for result in group)
        output_tokens = sum(result.output_tokens for result in group)
        rows.append(
            {
                "matchup": label,
                "player_count": player_count,
                "games": len(group),
                "good_wins": good_wins,
                "good_win_rate": rate(good_wins, len(group)),
                "good_win_interval": wilson_interval(good_wins, len(group)),
                "reasons": dict(sorted(reasons.items())),
                "mean_events": sum(result.events for result in group) / len(group),
                "llm_turns": llm_turns,
                "llm_fallback_rate": rate(sum(r.llm_fallbacks for r in group), llm_turns),
                "tokens_per_game": (input_tokens + output_tokens) / len(group),
                "cost_per_game_usd": (
                    pricing.cost(input_tokens, output_tokens) / len(group) if pricing else None
                ),
            }
        )
    return {"rows": rows}
