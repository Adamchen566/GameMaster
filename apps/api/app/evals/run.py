"""Run the evaluation and write a report.

    python -m app.evals.run --provider scripted --out eval-out
    python -m app.evals.run --provider random --suites arena --random-games 1000
    python -m app.evals.run --provider anthropic --confirm-cost --out eval-out

Providers:

- `random`     no model at all; only the whole-game baseline (random against random).
- `scripted`   a stand-in that always answers legally. Checks the harness, costs nothing.
- `hostile`    a stand-in that misbehaves on purpose. Checks the guards, costs nothing.
- `anthropic`  Claude through the API. Every case is a paid request, so it needs
               `--confirm-cost` and credentials in the environment.
- `deepseek`   DeepSeek through its API: paid, so it also needs `--confirm-cost`.
- `codex`      Codex on this computer, on the ChatGPT subscription it is logged in to.
- `claude_code` Claude Code on this computer, on its Claude subscription.

The local clients cost no API money but use up a subscription's quota, and
each answer takes seconds, so they take `--limit` and `--suites` seriously.

The exit code is 1 if a safety invariant broke: an illegal action was accepted,
a secret was sent to a model, or the game master showed a role it cannot know.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.agents.llm_player import STYLES, LlmPlayer
from app.agents.model import ModelClient, Pricing, TokenBudget
from app.config import Settings
from app.evals import arena, gm_eval, player_eval, report
from app.evals.cases import load_gm_cases, load_player_cases
from app.evals.models import HostileModel, ScriptedModel

PROVIDERS = ("random", "scripted", "hostile", "anthropic", "deepseek", "codex", "claude_code")
PAID = ("anthropic", "deepseek")
"""Providers billed per request; a run needs `--confirm-cost`."""
LOCAL = ("codex", "claude_code")
SUITES = ("players", "gm", "arena")
PLAYER_COUNTS = (5, 6, 7, 8, 9, 10)


def build_model(provider: str, settings: Settings) -> tuple[ModelClient | None, str]:
    match provider:
        case "random":
            return None, "none (random legal bot)"
        case "scripted":
            return ScriptedModel(), "scripted stand-in (not a language model)"
        case "hostile":
            return HostileModel(), "hostile stand-in (not a language model)"
        case "anthropic":
            # Imported here so the SDK is only loaded when it is used.
            from app.agents.anthropic_model import AnthropicModel

            model = AnthropicModel(model=settings.llm_model, effort=settings.llm_effort)
            return model, f"{settings.llm_model} (effort {settings.llm_effort})"
        case "deepseek" | "codex" | "claude_code":
            from app.agents.drivers import build_drivers

            # Asked for by name: the server's LLM_DRIVERS switch is for the lobby, not here.
            driver = build_drivers(settings.model_copy(update={"llm_drivers": provider}))[provider]
            if driver.model is None:
                raise SystemExit(f"{driver.label} cannot be used here: {driver.problem}.")
            return driver.model, driver.label
        case other:
            raise ValueError(f"Unknown provider '{other}'.")


def timeouts(provider: str, settings: Settings) -> tuple[float, float]:
    """`(player, game master)` seconds to wait for one answer from this provider."""
    match provider:
        case "codex":
            return settings.codex_timeout_seconds, settings.codex_timeout_seconds
        case "claude_code":
            return settings.claude_code_timeout_seconds, settings.claude_code_timeout_seconds
        case _:
            return settings.llm_player_timeout_seconds, settings.llm_gm_timeout_seconds


def _pricing(settings: Settings) -> Pricing | None:
    input_price, output_price = (
        settings.llm_input_price_per_mtok,
        settings.llm_output_price_per_mtok,
    )
    if input_price is None or output_price is None:
        return None
    return Pricing(input_price, output_price)


def invariant_failures(
    players: Sequence[player_eval.PlayerResult], narrations: Sequence[gm_eval.GmResult]
) -> list[str]:
    """Things that must hold for any model. A non-empty list fails the run."""
    failures = [
        f"{result.case.id}: an illegal action was accepted"
        for result in players
        if not result.final_action_legal
    ]
    failures += [
        f"{result.case.id}: secrets sent to the model ({', '.join(result.observation_leaks)})"
        for result in players
        if result.observation_leaks
    ]
    for narration in narrations:
        case_id = narration.case.id
        if not narration.facts_match_template:
            failures.append(f"{case_id}: the stated facts differ from the template")
        if not narration.hint_is_official:
            failures.append(f"{case_id}: the rule hint is not official text")
        if not narration.within_limit:
            failures.append(f"{case_id}: the shown line is empty or too long")
        if narration.names_role:
            failures.append(f"{case_id}: the shown line names a role")
        if narration.question_leaks:
            failures.append(f"{case_id}: secrets sent to the model")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the AI players and the game master.")
    parser.add_argument("--provider", choices=PROVIDERS, default="scripted")
    parser.add_argument(
        "--suites", default=",".join(SUITES), help="comma-separated: " + ", ".join(SUITES)
    )
    parser.add_argument("--style", choices=STYLES, default="baseline")
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases per suite")
    parser.add_argument(
        "--random-games", type=int, default=200, help="baseline games per player count"
    )
    parser.add_argument(
        "--model-games", type=int, default=2, help="model games per player count and side"
    )
    parser.add_argument("--players", default="5,7,10", help="player counts for model games")
    parser.add_argument("--out", type=Path, default=None, help="directory for the report files")
    parser.add_argument("--confirm-cost", action="store_true", help="required for a paid provider")
    args = parser.parse_args(argv)

    suites = [suite for suite in args.suites.split(",") if suite]
    unknown = sorted(set(suites) - set(SUITES))
    if unknown:
        parser.error(f"unknown suite(s): {', '.join(unknown)}")
    if args.provider in PAID and not args.confirm_cost:
        parser.error(
            f"--provider {args.provider} sends paid requests; pass --confirm-cost to go ahead"
        )

    settings = Settings()
    pricing = _pricing(settings) if args.provider == "anthropic" else None
    model, model_name = build_model(args.provider, settings)
    player_timeout, gm_timeout = timeouts(args.provider, settings)

    players: list[player_eval.PlayerResult] | None = None
    narrations: list[gm_eval.GmResult] | None = None
    player_summary = gm_summary = arena_summary = None

    if model is not None and "players" in suites:
        players = player_eval.run_cases(
            load_player_cases()[: args.limit],
            model,
            style=args.style,
            timeout_seconds=player_timeout,
        )
        player_summary = player_eval.summarise(players, pricing)

    if model is not None and "gm" in suites:
        narrations = gm_eval.run_cases(
            load_gm_cases()[: args.limit], model, timeout_seconds=gm_timeout
        )
        gm_summary = gm_eval.summarise(narrations, pricing)

    if "arena" in suites:
        matches = arena.play_series(
            PLAYER_COUNTS, args.random_games, arena.Matchup("random", "random")
        )
        # The reasoning bot that fills seats in real games, against itself and against random.
        for baseline in (
            arena.Matchup("bot", "bot"),
            arena.Matchup("bot", "random"),
            arena.Matchup("random", "bot"),
        ):
            matches += arena.play_series(PLAYER_COUNTS, args.random_games, baseline)
        if model is not None:
            # A local client is counted, never cut off: it is not billed per token.
            ceiling = 10**15 if args.provider in LOCAL else settings.llm_max_tokens_per_game
            budget = TokenBudget(ceiling, pricing)
            llm = LlmPlayer(model, budget, style=args.style, timeout_seconds=player_timeout)
            counts = [int(count) for count in args.players.split(",") if count]
            for matchup in (
                arena.Matchup("llm", "random"),
                arena.Matchup("random", "llm"),
                arena.Matchup("llm", "bot"),
                arena.Matchup("bot", "llm"),
            ):
                matches += arena.play_series(
                    counts, args.model_games, matchup, llm=llm, budget=budget
                )
        arena_summary = arena.summarise(matches, pricing)

    text = report.markdown(
        provider=args.provider,
        model_name=model_name,
        players=players,
        player_summary=player_summary,
        narrations=narrations,
        gm_summary=gm_summary,
        arena_summary=arena_summary,
    )
    failures = invariant_failures(players or [], narrations or [])
    print(text)

    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.md").write_text(text, encoding="utf-8", newline="\n")
        results: dict[str, Any] = {
            "provider": args.provider,
            "model": model_name,
            "summary": {"players": player_summary, "gm": gm_summary, "arena": arena_summary},
            "players": report.raw(players or []),
            "gm": report.raw(narrations or []),
            "invariant_failures": failures,
        }
        (args.out / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
            newline="\n",
        )
        if narrations is not None:
            (args.out / "gm_labels.csv").write_text(
                report.label_sheet(narrations), encoding="utf-8-sig", newline="\n"
            )

    if failures:
        print("\nINVARIANT FAILURES")
        for failure in failures:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
