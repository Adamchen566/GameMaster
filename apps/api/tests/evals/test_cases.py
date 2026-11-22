"""The committed case files are what they claim to be, and cover what the roadmap asks."""

from __future__ import annotations

from collections import Counter

import pytest

from app.evals import build_cases
from app.evals.cases import (
    GM_ATTACK_NAMES,
    PLANTED_NOTE,
    PLAYER_ATTACK_NAMES,
    SPEECH_ATTACKS,
    GmCase,
    PlayerCase,
    load_gm_cases,
    load_player_cases,
    resolve_gm,
    resolve_player,
)
from app.game.state import MissionOutcome

PLAYER_CASES = load_player_cases()
GM_CASES = load_gm_cases()


def test_there_are_enough_cases() -> None:
    assert len(PLAYER_CASES) >= 80
    assert len(GM_CASES) >= 30


def test_case_ids_are_unique() -> None:
    ids = [case.id for case in (*PLAYER_CASES, *GM_CASES)]
    assert len(ids) == len(set(ids))


def test_committed_files_are_exactly_what_the_builder_produces() -> None:
    """Editing a file by hand, or changing the simulator, must not go unnoticed."""
    assert build_cases.player_cases() == PLAYER_CASES
    assert build_cases.gm_cases() == GM_CASES


@pytest.mark.parametrize("case", PLAYER_CASES, ids=lambda case: case.id)
def test_player_case_is_the_position_it_describes(case: PlayerCase) -> None:
    position = resolve_player(case)
    seat = position.state.find_player(case.seat)

    assert seat is not None and seat.role is not None
    assert seat.role.value == case.role
    assert position.state.phase.value == case.phase
    assert len(position.state.players) == case.player_count
    assert position.view.you_id == case.seat
    assert position.view.legal_actions, "the seat must have a decision to make"


def test_player_cases_cover_every_player_count_role_and_phase() -> None:
    seen = {(case.player_count, case.role, case.phase) for case in PLAYER_CASES}

    for player_count in range(5, 11):
        for role in ("merlin", "loyal_servant", "assassin", "minion"):
            for phase in ("team_proposal", "team_vote", "mission_vote"):
                assert (player_count, role, phase) in seen
        assert (player_count, "assassin", "assassination") in seen


def test_player_cases_are_not_all_from_the_opening() -> None:
    missions = Counter(
        resolve_player(case).view.current_mission_number
        for case in PLAYER_CASES
        if case.phase != "assassination"
    )
    assert len(missions) >= 4


def test_every_attack_is_tried_in_both_languages() -> None:
    seen = {(case.attack, case.language) for case in PLAYER_CASES if case.attack}
    assert seen == {
        (attack, language) for attack in PLAYER_ATTACK_NAMES for language in ("zh", "en")
    }


def test_attack_text_reaches_the_position_through_a_name_or_the_notes() -> None:
    for case in PLAYER_CASES:
        position = resolve_player(case)
        if case.attack is None:
            assert position.note == ""
            assert all(name.split()[-1].isdigit() for name in position.names.values())
        elif case.attack == "act_for_another":
            assert position.note == PLANTED_NOTE
        elif case.attack in SPEECH_ATTACKS:
            hostile = SPEECH_ATTACKS[case.attack][case.language]
            said = [e for e in position.history if e.kind == "speech" and e.data["text"] == hostile]
            assert len(said) == 1
            assert said[0].data["player"] != case.seat, "the attack comes from another player"
            assert all(name.split()[-1].isdigit() for name in position.names.values())
        else:
            hostile = PLAYER_ATTACK_NAMES[case.attack][case.language]
            carriers = [pid for pid, name in position.names.items() if name == hostile]
            assert len(carriers) == 1
            assert carriers[0] != case.seat, "the attack comes from another player"


def test_last_proposal_cases_are_on_the_last_proposal() -> None:
    cases = [case for case in PLAYER_CASES if case.expect == "approve"]
    assert len(cases) >= 3
    for case in cases:
        view = resolve_player(case).view
        assert view.proposal_number == view.max_rejected_proposals
        assert case.role in ("merlin", "loyal_servant")


def test_fail_wins_cases_are_one_fail_card_from_victory() -> None:
    cases = [case for case in PLAYER_CASES if case.expect == "fail"]
    assert len(cases) >= 3
    for case in cases:
        view = resolve_player(case).view
        failed = sum(mission.outcome is MissionOutcome.FAIL for mission in view.missions)
        current = next(m for m in view.missions if m.number == view.current_mission_number)
        assert failed == view.missions_to_win - 1
        assert current.fails_required == 1
        assert view.legal_actions[0].can_fail


@pytest.mark.parametrize("case", GM_CASES, ids=lambda case: case.id)
def test_gm_case_is_the_event_it_describes(case: GmCase) -> None:
    position = resolve_gm(case)

    assert position.entry.kind == case.kind
    assert position.entry.version == case.version
    assert len(position.names) == case.player_count
    if case.attack is not None:
        assert GM_ATTACK_NAMES[case.attack][case.language] in position.names.values()


def test_gm_cases_cover_every_event_in_both_languages_and_every_attack() -> None:
    plain = {(case.kind, case.language) for case in GM_CASES if case.attack is None}
    assert plain == {(kind, language) for kind in build_cases.GM_KINDS for language in ("zh", "en")}

    attacks = {(case.attack, case.language) for case in GM_CASES if case.attack}
    assert attacks == {
        (attack, language) for attack in GM_ATTACK_NAMES for language in ("zh", "en")
    }


def test_unknown_length_or_version_is_an_error() -> None:
    player = PLAYER_CASES[0]
    with pytest.raises(ValueError, match="never has exactly"):
        resolve_player(PlayerCase(**{**_fields(player), "length": 10_000}))

    narration = GM_CASES[0]
    with pytest.raises(ValueError, match="no public event"):
        resolve_gm(GmCase(**{**_fields(narration), "version": 10_000}))


def _fields(case: PlayerCase | GmCase) -> dict[str, object]:
    return {name: getattr(case, name) for name in case.__slots__}


def test_a_planted_speech_is_on_the_table_while_the_proposal_is_discussed() -> None:
    cases = [case for case in PLAYER_CASES if case.attack in SPEECH_ATTACKS]
    assert {case.attack for case in cases} == set(SPEECH_ATTACKS)
    for case in cases:
        position = resolve_player(case)
        if case.phase in ("discussion", "team_vote"):
            texts = [speech.text for speech in position.view.speeches]
            assert SPEECH_ATTACKS[case.attack][case.language] in texts
        # The game itself is untouched: the seat may still do exactly what it could.
        assert position.view.legal_actions


def test_merlin_naming_itself_misses_the_secret_keeping_expectation() -> None:
    from app.evals.player_eval import meets
    from app.game.actions import Speak

    case = next(case for case in PLAYER_CASES if case.expect == "keeps_secret")
    view = resolve_player(case).view
    said = lambda text: Speak(player_id=view.you_id, text=text, expected_version=view.version)

    assert meets("keeps_secret", view, said("我同意这一队。")) is True
    assert meets("keeps_secret", view, said("好吧，我是梅林。")) is False
    assert meets("keeps_secret", view, said("Fine, I am Merlin.")) is False
