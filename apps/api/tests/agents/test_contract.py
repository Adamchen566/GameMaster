"""What a model is told, and what it is allowed to answer."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.agents.contract import (
    DECISION_SCHEMA,
    HISTORY_LIMIT,
    NOTE_LIMIT,
    InvalidDecision,
    build_observation,
    clean_name,
    decision_from_data,
    to_action,
)
from app.game.actions import Assassinate, ProposeTeam, Speak, VoteMission, VoteTeam
from app.game.engine import apply_action, replay
from app.game.public_log import public_log
from app.game.rulesets import Alignment, Role
from app.game.simulate import play_random_game
from app.game.state import GameState, Phase
from app.game.views import build_player_view
from tests.agents.support import NAMES, decision, position
from tests.game.scenarios import id_with_role, ids_with_alignment, started
from tests.game.test_views import FULL_CAST

# --- The observation: nothing a human in that seat would not know ------------


def observe(state: GameState, player_id: str, **kwargs: Any) -> dict[str, Any]:
    view = build_player_view(state, player_id)
    observation = build_observation(view, names=NAMES, history=(), **kwargs)
    # Round-trip through JSON: what is checked is exactly what would be sent.
    sent: dict[str, Any] = json.loads(json.dumps(observation.data))
    return sent


def known(observation: dict[str, Any]) -> dict[str, str | None]:
    return {player["id"]: player["known_to_you_as"] for player in observation["players"]}


def full_cast_game() -> GameState:
    """The official decks only use the basic roles, so deal the ruleset that has them all."""
    state = started(player_count=10, seed=3, ruleset=FULL_CAST)
    assert {player.role for player in state.players} == {
        Role.MERLIN,
        Role.PERCIVAL,
        Role.LOYAL_SERVANT,
        Role.ASSASSIN,
        Role.MORGANA,
        Role.MORDRED,
        Role.OBERON,
    }
    return state


def test_observation_matrix_for_every_role() -> None:
    state = full_cast_game()
    role_of = {player.id: player.role for player in state.players}
    evil = set(ids_with_alignment(state, Alignment.EVIL))
    merlin, morgana = id_with_role(state, Role.MERLIN), id_with_role(state, Role.MORGANA)
    mordred, oberon = id_with_role(state, Role.MORDRED), id_with_role(state, Role.OBERON)

    for player_id, role in role_of.items():
        seen = {other: mark for other, mark in known(observe(state, player_id)).items() if mark}
        match role:
            case Role.MERLIN:
                assert seen == {other: "evil" for other in evil - {mordred}}
            case Role.PERCIVAL:
                assert seen == {merlin: "merlin_or_morgana", morgana: "merlin_or_morgana"}
            case Role.ASSASSIN | Role.MORGANA | Role.MORDRED | Role.MINION:
                assert seen == {other: "evil" for other in evil - {oberon, player_id}}
            case Role.OBERON | Role.LOYAL_SERVANT:
                assert seen == {}
            case other:
                raise AssertionError(f"unexpected role {other}")


def test_observation_names_no_role_but_your_own() -> None:
    state = full_cast_game()
    role_names = {role.value for role in Role}

    for player in state.players:
        observation = observe(state, player.id)
        assert observation["you"]["role"] == player.role
        assert observation["you"]["alignment"] == player.role.alignment  # type: ignore[union-attr]

        def strings(value: object) -> list[str]:
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                return [text for item in value.values() for text in strings(item)]
            if isinstance(value, list):
                return [text for item in value for text in strings(item)]
            return []

        mentioned = [text for text in strings(observation) if text in role_names]
        assert mentioned == [player.role]


def test_observation_never_contains_the_seed_or_individual_mission_cards() -> None:
    game = play_random_game(player_count=7, seed=5)
    log = public_log(game.events)
    for length in range(1, len(game.events)):
        state = replay(game.initial, game.events[:length])
        if state.phase is Phase.FINISHED:
            break
        for player in state.players:
            view = build_player_view(state, player.id)
            data = build_observation(view, names=NAMES, history=log[:length]).data
            text = json.dumps(data)
            assert "seed" not in text
            assert "mission_vote_cast" not in text
            assert "game_started" not in text


def test_history_is_cut_to_the_most_recent_entries() -> None:
    log = max(
        (public_log(play_random_game(player_count=10, seed=seed).events) for seed in range(20)),
        key=len,
    )
    game = play_random_game(player_count=10, seed=3)
    assert len(log) > HISTORY_LIMIT
    state = replay(game.initial, game.events[:3])

    data = build_observation(build_player_view(state, "p1"), names=NAMES, history=log).data

    assert data["public_history"] == [entry.to_json() for entry in log[-HISTORY_LIMIT:]]


def test_notes_are_cut_to_a_fixed_length() -> None:
    state, _ = position(Phase.TEAM_VOTE)

    assert len(observe(state, "p1", note="x" * 5000)["your_notes"]) == NOTE_LIMIT


@pytest.mark.parametrize(
    ("typed", "shown"),
    [
        ("Adam", "Adam"),
        ("  Ada   m  ", "Ada m"),
        ("line1\nline2\ttab", "line1 line2 tab"),
        ("a\x00b\x1b[31mc", "ab[31mc"),
        ("x" * 50, "x" * 20),
    ],
)
def test_names_are_made_single_line_printable_and_short(typed: str, shown: str) -> None:
    assert clean_name(typed) == shown


def test_schema_requires_every_field_and_allows_no_others() -> None:
    assert set(DECISION_SCHEMA["required"]) == set(DECISION_SCHEMA["properties"])
    assert DECISION_SCHEMA["additionalProperties"] is False
    assert "start_game" not in DECISION_SCHEMA["properties"]["action"]["enum"]


# --- The decision: only legal actions, only ids from legal_actions -----------


@pytest.mark.parametrize(
    "broken",
    [
        "propose_team",
        ["vote_team"],
        None,
        {},
        decision(approve="yes"),
        decision(approve=1),
        decision(success=None),
        decision(team="p1"),
        decision(team=["p1", 2]),
        decision(target_id=None),
        decision(note=7),
        decision(action=None),
        {key: value for key, value in decision().items() if key != "note"},
    ],
)
def test_malformed_answers_are_refused(broken: object) -> None:
    with pytest.raises(InvalidDecision):
        decision_from_data(broken)


def test_wellformed_answer_is_parsed_and_its_note_cut() -> None:
    parsed = decision_from_data(decision(action="propose_team", team=["p1", "p2"], note="n" * 999))

    assert (parsed.action, parsed.team) == ("propose_team", ("p1", "p2"))
    assert len(parsed.note) == NOTE_LIMIT


def actor(state: GameState) -> str:
    return next(
        player.id for player in state.players if build_player_view(state, player.id).legal_actions
    )


def test_legal_proposal_becomes_an_action_the_engine_accepts() -> None:
    state, _ = position(Phase.TEAM_PROPOSAL)
    view = build_player_view(state, actor(state))
    legal = view.legal_actions[0]
    team = list(legal.targets[: legal.team_size])

    action = to_action(view, decision_from_data(decision(action="propose_team", team=team)))

    assert action == ProposeTeam(
        player_id=view.you_id, team=tuple(team), expected_version=view.version
    )
    apply_action(state, action)


@pytest.mark.parametrize(
    "team",
    [
        [],
        ["p1"],
        ["p1", "p1", "p2"],
        ["p1", "p2", "ghost"],
        ["p1", "p2", "p3", "p4", "p5", "p6", "p7"],
    ],
)
def test_illegal_teams_are_refused(team: list[str]) -> None:
    state, _ = position(Phase.TEAM_PROPOSAL)
    view = build_player_view(state, actor(state))

    with pytest.raises(InvalidDecision):
        to_action(view, decision_from_data(decision(action="propose_team", team=team)))


def test_action_that_is_not_yours_right_now_is_refused() -> None:
    state, _ = position(Phase.TEAM_VOTE)
    view = build_player_view(state, actor(state))

    for other in ("propose_team", "vote_mission", "assassinate", "start_game", "reveal_roles"):
        with pytest.raises(InvalidDecision, match="You may only do: vote_team"):
            to_action(view, decision_from_data(decision(action=other)))

    vote = to_action(view, decision_from_data(decision(action="vote_team", approve=False)))
    assert vote == VoteTeam(player_id=view.you_id, approve=False, expected_version=view.version)


def test_good_player_cannot_be_talked_into_failing_a_mission() -> None:
    state, _ = position(Phase.MISSION_VOTE)
    good = next(
        player.id
        for player in state.players
        if player.role is not None
        and player.role.alignment is Alignment.GOOD
        and build_player_view(state, player.id).legal_actions
    )
    view = build_player_view(state, good)

    with pytest.raises(InvalidDecision, match="may not play a fail card"):
        to_action(view, decision_from_data(decision(action="vote_mission", success=False)))

    played = to_action(view, decision_from_data(decision(action="vote_mission", success=True)))
    assert played == VoteMission(player_id=good, success=True, expected_version=view.version)


def test_assassin_may_only_name_a_listed_target() -> None:
    state, _ = position(Phase.ASSASSINATION)
    view = build_player_view(state, id_with_role(state, Role.ASSASSIN))
    targets = view.legal_actions[0].targets

    for target in ("ghost", view.you_id, ""):
        assert target not in targets
        with pytest.raises(InvalidDecision, match="target_id"):
            to_action(view, decision_from_data(decision(action="assassinate", target_id=target)))

    shot = to_action(view, decision_from_data(decision(action="assassinate", target_id=targets[0])))
    assert shot == Assassinate(
        player_id=view.you_id, target_id=targets[0], expected_version=view.version
    )


def test_every_action_is_issued_in_the_viewers_own_name() -> None:
    """There is no field in a decision that says who is acting."""
    state, _ = position(Phase.TEAM_VOTE)
    view = build_player_view(state, actor(state))
    answer = {**decision(action="vote_team"), "player_id": "p7"}

    action = to_action(view, decision_from_data(answer))

    assert action.player_id == view.you_id


def test_a_player_with_nothing_to_do_can_do_nothing() -> None:
    state, _ = position(Phase.TEAM_PROPOSAL)
    idle = next(
        player.id
        for player in state.players
        if not build_player_view(state, player.id).legal_actions
    )

    with pytest.raises(InvalidDecision, match="You may only do: nothing"):
        to_action(build_player_view(state, idle), decision_from_data(decision()))


# --- Speaking ------------------------------------------------------------------


def speaking() -> tuple[GameState, str]:
    state, _ = position(Phase.DISCUSSION)
    assert state.next_speaker_id is not None
    return state, state.next_speaker_id


def test_a_speech_is_made_in_this_seats_name_and_cleaned() -> None:
    state, speaker = speaking()
    view = build_player_view(state, speaker)
    target = view.legal_actions[0].targets[0]
    answer = decision(action="speak", speech="  I doubt\nthis team. ", suspects=[target])

    action = to_action(view, decision_from_data(answer))

    assert action == Speak(
        player_id=speaker,
        text="I doubt this team.",
        suspects=(target,),
        expected_version=view.version,
    )
    apply_action(state, action)


def test_a_speech_that_runs_on_is_cut_not_refused() -> None:
    state, speaker = speaking()
    view = build_player_view(state, speaker)

    action = to_action(view, decision_from_data(decision(action="speak", speech="x" * 900)))

    assert isinstance(action, Speak) and len(action.text) == 200
    apply_action(state, action)


@pytest.mark.parametrize("suspects", [["self"], ["p999"], ["dup", "dup"], ["a", "b", "c", "d"]])
def test_suspects_must_come_from_the_offered_targets(suspects: list[str]) -> None:
    state, speaker = speaking()
    view = build_player_view(state, speaker)
    targets = view.legal_actions[0].targets
    named = {"self": speaker, "dup": targets[0], "a": targets[0], "b": targets[1]}
    named |= {"c": targets[2], "d": targets[3]}
    answer = decision(action="speak", suspects=[named.get(item, item) for item in suspects])

    with pytest.raises(InvalidDecision, match="suspects"):
        to_action(view, decision_from_data(answer))


def test_suspects_must_be_a_list_of_strings() -> None:
    with pytest.raises(InvalidDecision, match="suspects"):
        decision_from_data(decision(suspects=[1, 2]))
    with pytest.raises(InvalidDecision, match="suspects"):
        decision_from_data(decision(suspects="p2"))
    with pytest.raises(InvalidDecision, match="speech"):
        decision_from_data(decision(speech=None))


def test_nobody_speaks_when_it_is_not_their_turn() -> None:
    state, speaker = speaking()
    waiting = next(pid for pid in state.player_ids if pid != speaker)

    with pytest.raises(InvalidDecision, match="not available"):
        to_action(build_player_view(state, waiting), decision_from_data(decision(action="speak")))


def test_a_player_is_told_what_has_been_said_so_far() -> None:
    game = play_random_game(player_count=5, seed=3)
    spoken = [index for index, event in enumerate(game.events) if event.type == "player_spoke"]
    events = game.events[: spoken[1] + 1]
    state = replay(game.initial, events)
    assert state.next_speaker_id is not None
    view = build_player_view(state, state.next_speaker_id)

    sent = build_observation(view, names=NAMES, history=public_log(events)).data

    assert [speech["player"] for speech in sent["speeches_on_this_proposal"]] == [
        speech.player_id for speech in state.speeches
    ]
    assert sent["legal_actions"][0]["type"] == "speak"
    assert [entry["kind"] for entry in sent["public_history"]].count("speech") == 2
