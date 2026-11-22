"""Turn evaluation results into files: a Markdown report, raw JSON and a labelling sheet."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from app.evals.gm_eval import GmResult
from app.evals.player_eval import PlayerResult

FAILED_SAMPLE_LIMIT = 15

_PLAYER_ROWS: tuple[tuple[str, str], ...] = (
    ("cases", "Cases"),
    ("final_action_legal_rate", "Final action legal (after retry and fallback)"),
    ("first_answer_legal_rate", "First answer legal"),
    ("structured_output_rate", "First answer well-formed"),
    ("overreach_rate", "Reached beyond what was offered"),
    ("attack_overreach_rate", "... in the attack cases"),
    ("observation_leak_rate", "Secrets in the text sent to the model"),
    ("timeout_rate", "Timed out"),
    ("fallback_rate", "Turn handed to the random bot"),
    ("expectation_met_rate", "Made the one right move (where there is one)"),
    ("latency_p50_ms", "Latency P50 (ms)"),
    ("latency_p95_ms", "Latency P95 (ms)"),
    ("input_tokens", "Input tokens"),
    ("output_tokens", "Output tokens"),
    ("cost_usd", "Cost (USD)"),
)
_GM_ROWS: tuple[tuple[str, str], ...] = (
    ("cases", "Cases"),
    ("facts_match_template_rate", "Stated facts equal the template"),
    ("official_hint_rate", "Rule hint is official text"),
    ("within_limit_rate", "Line within the length limit"),
    ("role_named_rate", "Shown line names a role it cannot know"),
    ("question_leak_rate", "Secrets in the text sent to the model"),
    ("structured_output_rate", "Model line accepted"),
    ("template_fallback_rate", "Template used instead"),
    ("timeout_rate", "Timed out"),
    ("lines_for_human_review", "Model lines awaiting a human check"),
    ("latency_p50_ms", "Latency P50 (ms)"),
    ("latency_p95_ms", "Latency P95 (ms)"),
    ("input_tokens", "Input tokens"),
    ("output_tokens", "Output tokens"),
    ("cost_usd", "Cost (USD)"),
)


def _cell(key: str, value: object) -> str:
    if value is None:
        return "n/a"
    if key.endswith("_rate") and isinstance(value, float):
        return f"{value:.1%}"
    if key.endswith("_ms") and isinstance(value, float):
        return f"{value:.0f}"
    if key == "cost_usd" and isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _table(rows: Sequence[tuple[str, str]], summary: Mapping[str, Any]) -> list[str]:
    lines = ["| Metric | Value |", "| --- | --- |"]
    lines.extend(f"| {label} | {_cell(key, summary.get(key))} |" for key, label in rows)
    return lines


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _arena_table(summary: Mapping[str, Any]) -> list[str]:
    lines = [
        "| Matchup | Players | Games | Good wins | 95% interval | Model fallback | Tokens / game |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summary["rows"]:
        interval = row["good_win_interval"]
        shown = f"{interval[0]:.1%} - {interval[1]:.1%}" if interval else "n/a"
        lines.append(
            f"| {row['matchup']} | {row['player_count']} | {row['games']} "
            f"| {_percent(row['good_win_rate'])} | {shown} "
            f"| {_percent(row['llm_fallback_rate'])} | {row['tokens_per_game']:.0f} |"
        )
    return lines


def failed_players(results: Sequence[PlayerResult]) -> list[PlayerResult]:
    """Cases worth reading: anything that was not a clean, legal, first-time answer."""
    return [
        result
        for result in results
        if not result.final_action_legal
        or not result.first_answer_legal
        or result.overreach
        or result.observation_leaks
        or result.expectation_met is False
    ]


def markdown(
    *,
    provider: str,
    model_name: str,
    players: Sequence[PlayerResult] | None,
    player_summary: Mapping[str, Any] | None,
    narrations: Sequence[GmResult] | None,
    gm_summary: Mapping[str, Any] | None,
    arena_summary: Mapping[str, Any] | None,
) -> str:
    lines = ["# Evaluation run", "", f"- Provider: `{provider}`", f"- Model: `{model_name}`", ""]

    if players is not None and player_summary is not None:
        lines += ["## Player decisions", "", *_table(_PLAYER_ROWS, player_summary), ""]
        failed = failed_players(players)
        lines += [f"### Cases to read ({len(failed)} of {len(players)})", ""]
        if failed:
            lines += [
                "| Case | Role, phase | Attack | Ended with | Why it is listed |",
                "| --- | --- | --- | --- | --- |",
            ]
            for result in failed[:FAILED_SAMPLE_LIMIT]:
                why = ", ".join(
                    [
                        *result.overreach,
                        *result.observation_leaks,
                        *(["fallback:" + result.fallback_reason] if result.fallback_reason else []),
                        *(["missed the right move"] if result.expectation_met is False else []),
                        *(["ILLEGAL FINAL ACTION"] if not result.final_action_legal else []),
                    ]
                )
                case = result.case
                lines.append(
                    f"| {case.id} | {case.role}, {case.phase} | {case.attack or '-'} "
                    f"| {result.action} ({result.source}) | {why or 'first answer rejected'} |"
                )
            if len(failed) > FAILED_SAMPLE_LIMIT:
                lines.append(f"\n{len(failed) - FAILED_SAMPLE_LIMIT} more in `results.json`.")
        else:
            lines.append("None.")
        lines.append("")

    if narrations is not None and gm_summary is not None:
        lines += ["## Game master", "", *_table(_GM_ROWS, gm_summary), ""]
        lines += [
            "Whether a model-written line is true to the facts is not judged here.",
            "Mark each row of `gm_labels.csv` by hand.",
            "",
        ]

    if arena_summary is not None:
        lines += ["## Whole games", "", *_arena_table(arena_summary), ""]

    return "\n".join(lines)


def label_sheet(narrations: Sequence[GmResult]) -> str:
    """CSV of every model-written line, with empty columns for a person to fill in."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        [
            "case",
            "kind",
            "language",
            "attack",
            "facts",
            "model_line",
            "rule_hint",
            "consistent_with_facts (y/n)",
            "implies_hidden_information (y/n)",
            "notes",
        ]
    )
    for result in narrations:
        if result.source != "model":
            continue
        case = result.case
        writer.writerow(
            [
                case.id,
                case.kind,
                case.language,
                case.attack or "",
                result.facts,
                result.announcement,
                result.rule_hint,
                "",
                "",
                "",
            ]
        )
    return out.getvalue()


def raw(results: Sequence[PlayerResult] | Sequence[GmResult]) -> list[dict[str, Any]]:
    return [asdict(result) for result in results]
