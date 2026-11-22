"""The discussion: after a team is proposed, everyone speaks once before the vote."""

from __future__ import annotations

import pytest

from app.game.actions import Speak, VoteTeam
from app.game.engine import MAX_SUSPECTS, SPEECH_LIMIT, apply_action, clean_speech, replay
from app.game.errors import ErrorCode, RuleViolation
from app.game.events import PlayerSpoke
from app.game.public_log import public_log
from app.game.simulate import play_random_game
from app.game.state import GameState, Phase, Speech
from app.game.views import build_player_view
from tests.game.scenarios import act, discuss, leader_id, lobby, propose_only, started


def violation(state: GameState, action: Speak | VoteTeam) -> ErrorCode:
    with pytest.raises(RuleViolation) as error:
        apply_action(state, action)
    return error.value.code


def proposed(player_count: int = 5, seed: int = 1) -> GameState:
    return propose_only(started(player_count, seed))


def speaker(state: GameState) -> str:
    assert state.next_speaker_id is not None
    return state.next_speaker_id


def test_a_proposal_opens_the_discussion_not_the_vote() -> None:
    state = proposed()

    assert state.phase is Phase.DISCUSSION
    assert state.speeches == ()
    assert violation(state, VoteTeam(player_id="p1", approve=True)) is ErrorCode.WRONG_PHASE


@pytest.mark.parametrize("player_count", range(5, 11))
def test_the_leader_speaks_first_then_the_table_in_seat_order(player_count: int) -> None:
    state = proposed(player_count, seed=3)
    leader = leader_id(state)
    ids = state.player_ids
    start = ids.index(leader)
    expected = ids[start:] + ids[:start]

    order = []
    while state.phase is Phase.DISCUSSION:
        order.append(speaker(state))
        state = act(state, Speak(player_id=speaker(state), text="ok"))

    assert tuple(order) == expected
    assert order[0] == leader
    assert state.phase is Phase.TEAM_VOTE
    assert state.next_speaker_id is None


def test_nobody_speaks_out_of_turn_or_twice() -> None:
    state = proposed()
    first = speaker(state)
    someone_else = next(pid for pid in state.player_ids if pid != first)

    assert violation(state, Speak(player_id=someone_else)) is ErrorCode.NOT_YOUR_TURN_TO_SPEAK

    state = act(state, Speak(player_id=first, text="My team."))
    assert violation(state, Speak(player_id=first)) is ErrorCode.NOT_YOUR_TURN_TO_SPEAK


def test_speaking_is_only_possible_during_the_discussion() -> None:
    assert violation(started(), Speak(player_id="p1")) is ErrorCode.WRONG_PHASE
    assert violation(lobby(), Speak(player_id="p1")) is ErrorCode.WRONG_PHASE
    assert violation(discuss(proposed()), Speak(player_id="p1")) is ErrorCode.WRONG_PHASE


def test_a_speech_is_recorded_with_who_said_it_and_whom_they_doubt() -> None:
    state = proposed()
    first = speaker(state)
    others = [pid for pid in state.player_ids if pid != first]

    new_state, events = apply_action(
        state, Speak(player_id=first, text="I trust this team.", suspects=(others[2], others[0]))
    )

    # Stored in seat order, whatever order they were named in.
    in_seat_order = tuple(pid for pid in state.player_ids if pid in (others[0], others[2]))
    assert events == [
        PlayerSpoke(
            mission_number=1,
            proposal_number=1,
            player_id=first,
            text="I trust this team.",
            suspects=in_seat_order,
        )
    ]
    assert new_state.speeches == (
        Speech(player_id=first, text="I trust this team.", suspects=in_seat_order),
    )


def test_an_empty_speech_is_a_pass() -> None:
    state = proposed()
    new_state = act(state, Speak(player_id=speaker(state)))

    assert new_state.speeches[0].text == ""
    assert new_state.next_speaker_id != speaker(state)


def test_speech_is_made_single_line_and_printable() -> None:
    assert clean_speech("  hello \n\n  there\t!  ") == "hello there !"
    assert clean_speech("a\x00b\x1b[31mc") == "ab[31mc"

    state = proposed()
    new_state = act(state, Speak(player_id=speaker(state), text="line one\nline two"))
    assert new_state.speeches[0].text == "line one line two"


def test_a_speech_has_a_length_limit() -> None:
    state = proposed()
    who = speaker(state)

    assert act(state, Speak(player_id=who, text="x" * SPEECH_LIMIT)).speeches
    too_long = Speak(player_id=who, text="x" * (SPEECH_LIMIT + 1))
    assert violation(state, too_long) is ErrorCode.SPEECH_TOO_LONG
    # Padding does not count: the limit applies to what would be shown.
    assert act(state, Speak(player_id=who, text=" " * 500 + "hi")).speeches[0].text == "hi"


def test_suspects_must_be_other_players_named_once_and_not_too_many() -> None:
    state = proposed(7)
    who = speaker(state)
    others = tuple(pid for pid in state.player_ids if pid != who)

    def code(*suspects: str) -> ErrorCode:
        return violation(state, Speak(player_id=who, suspects=suspects))

    assert code(who) is ErrorCode.INVALID_SUSPECT
    assert code("ghost") is ErrorCode.INVALID_SUSPECT
    assert code(others[0], others[0]) is ErrorCode.INVALID_SUSPECT
    assert code(*others[: MAX_SUSPECTS + 1]) is ErrorCode.INVALID_SUSPECT
    assert act(state, Speak(player_id=who, suspects=others[:MAX_SUSPECTS])).speeches


def test_a_new_proposal_starts_a_new_round_of_speeches() -> None:
    state = proposed()
    state = act(state, Speak(player_id=speaker(state), text="first round"))
    state = discuss(state)
    for player_id in state.player_ids:
        state = act(state, VoteTeam(player_id=player_id, approve=False))

    # What was said stays on the table until the next team is named.
    assert state.phase is Phase.TEAM_PROPOSAL
    assert len(state.speeches) == len(state.players)

    state = propose_only(state)
    assert state.speeches == ()
    assert state.next_speaker_id == leader_id(state)


def test_everyone_sees_the_speeches_and_whose_turn_it_is() -> None:
    state = proposed()
    state = act(state, Speak(player_id=speaker(state), text="Hear me out."))

    for player_id in state.player_ids:
        view = build_player_view(state, player_id)
        assert view.speeches == state.speeches
        assert view.speaker_id == state.next_speaker_id
        may_speak = [legal for legal in view.legal_actions if legal.type == "speak"]
        assert bool(may_speak) == (player_id == state.next_speaker_id)
        if may_speak:
            assert set(may_speak[0].targets) == set(state.player_ids) - {player_id}


def test_speeches_are_in_the_public_log() -> None:
    state = proposed()
    spoken = []
    while state.phase is Phase.DISCUSSION:
        state, events = apply_action(state, Speak(player_id=speaker(state), text="noted"))
        spoken.extend(events)

    log = public_log(spoken, first_version=10)

    assert [entry.kind for entry in log] == ["speech"] * len(state.players)
    assert log[0].version == 10
    assert log[0].data["text"] == "noted"
    assert log[0].data["player"] == leader_id(state)
    assert log[0].data["suspects"] == []


def test_replaying_a_discussion_rebuilds_the_same_state() -> None:
    game = play_random_game(player_count=6, seed=9)
    first = next(index for index, event in enumerate(game.events) if isinstance(event, PlayerSpoke))
    midway = replay(game.initial, game.events[: first + 3])

    assert midway.phase is Phase.DISCUSSION
    assert len(midway.speeches) == 3
    assert replay(game.initial, game.events) == game.final
