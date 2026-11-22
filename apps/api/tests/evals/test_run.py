"""The command line: what it writes and when it refuses or fails."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.evals import gm_eval, player_eval
from app.evals.cases import load_gm_cases, load_player_cases
from app.evals.models import ScriptedModel
from app.evals.run import invariant_failures, main

QUICK = ["--limit", "6", "--random-games", "2", "--model-games", "1", "--players", "5"]


def test_scripted_run_writes_a_report_results_and_a_label_sheet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--provider", "scripted", "--out", str(tmp_path), *QUICK]) == 0

    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "## Player decisions" in report
    assert "## Game master" in report
    assert "## Whole games" in report
    assert "good=llm, evil=random" in report
    assert "not a language model" in report
    assert "## Whole games" in capsys.readouterr().out

    results = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert results["provider"] == "scripted"
    assert results["invariant_failures"] == []
    assert len(results["players"]) == 6 and len(results["gm"]) == 6
    assert results["summary"]["players"]["final_action_legal_rate"] == 1.0

    sheet = (tmp_path / "gm_labels.csv").read_text(encoding="utf-8-sig")
    assert len(sheet.strip().splitlines()) == 7


def test_hostile_run_passes_because_the_guards_hold(tmp_path: Path) -> None:
    assert main(["--provider", "hostile", "--out", str(tmp_path), *QUICK]) == 0

    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "### Cases to read" in report
    assert "fallback:" in report


def test_random_provider_only_plays_the_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--provider", "random", "--random-games", "3", "--out", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "good=random, evil=random" in out
    assert "Player decisions" not in out and "good=llm" not in out
    assert not (tmp_path / "gm_labels.csv").exists()


def test_one_suite_can_be_run_alone(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--provider", "scripted", "--suites", "gm", "--limit", "2"]) == 0

    out = capsys.readouterr().out
    assert "## Game master" in out
    assert "Player decisions" not in out and "Whole games" not in out


def test_paid_provider_needs_explicit_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--provider", "anthropic"])

    assert stopped.value.code == 2
    assert "--confirm-cost" in capsys.readouterr().err


def test_unknown_suite_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--suites", "players,vibes"])
    assert "unknown suite" in capsys.readouterr().err


def test_broken_invariants_are_named_and_fail_the_run() -> None:
    player = player_eval.run_case(load_player_cases()[0], ScriptedModel())
    narration = gm_eval.run_case(load_gm_cases()[0], ScriptedModel())
    assert invariant_failures([player], [narration]) == []

    failures = invariant_failures(
        [
            replace(player, final_action_legal=False),
            replace(player, observation_leaks=("role:merlin",)),
        ],
        [
            replace(narration, facts_match_template=False),
            replace(narration, hint_is_official=False),
            replace(narration, within_limit=False),
            replace(narration, names_role=True),
            replace(narration, question_leaks=("role:merlin",)),
        ],
    )

    assert len(failures) == 7
    assert "illegal action" in failures[0]
    assert "role:merlin" in failures[1]
