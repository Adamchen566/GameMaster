"""The table bot: it reasons from public evidence, says why, and votes as it spoke."""

from __future__ import annotations

import random
from collections.abc import Callable

import pytest

from app.agents.table_bot import chance_of_evil, choose_action, read_table
from app.game.actions import (
    Action,
    Assassinate,
    ProposeTeam,
    Speak,
    StartGame,
    VoteMission,
    VoteTeam,
)
from app.game.engine import apply_action
from app.game.events import GameEvent
from app.game.public_log import public_log
from app.game.rulesets import Alignment, Role
from app.game.state import GameState, MissionOutcome, Phase
from app.game.views import build_player_view
from tests.game.invariants import check_invariants
from tests.game.scenarios import (
    id_with_role,
    ids_with_alignment,
    lobby,
    player_ids,
)

NAMES = {f"p{number}": f"Player {number}" for number in range(1, 11)}


class Game:
    """A game driven action by action, keeping the events for the public log."""

    def __init__(self, player_count: int = 5, seed: int = 1) -> None:
        self.seed = seed
        self.state, self.events = apply_action(
            lobby(player_count), StartGame(player_id="p1", seed=seed)
        )

    def do(self, action: Action) -> list[GameEvent]:
        self.state, events = apply_action(self.state, action)
        self.events.extend(events)
        check_invariants(self.state)
        return events

    def actor(self) -> str:
        return next(
            pid for pid in self.state.player_ids if build_player_view(self.state, pid).legal_actions
        )

    def bot(self, player_id: str, language: str = "en") -> Action:
        view = build_player_view(self.state, player_id)
        return choose_action(
            view,
            random.Random(f"{self.seed}:{player_id}:{view.version}"),
            history=public_log(self.events),
            names=NAMES,
            language="zh" if language == "zh" else "en",
            salt=str(self.seed),
        )

    def step(self) -> Action:
        action = self.bot(self.actor())
        self.do(action)
        return action

    def play_until(self, done: Callable[[GameState], bool]) -> None:
        while not done(self.state):
            assert self.state.phase is not Phase.FINISHED, "the game ended first"
            self.step()

    def fail_first_mission(self) -> tuple[str, str]:
        """Mission 1 goes out with one evil player and fails. Returns (good, evil) on it."""
        evil = ids_with_alignment(self.state, Alignment.EVIL)[0]
        good = next(
            pid
            for pid in ids_with_alignment(self.state, Alignment.GOOD)
            if self.state.find_player(pid).role is Role.LOYAL_SERVANT  # type: ignore[union-attr]
        )
        assert self.state.leader_id is not None
        self.do(ProposeTeam(player_id=self.state.leader_id, team=(good, evil)))
        while self.state.phase is Phase.DISCUSSION:
            assert self.state.next_speaker_id is not None
            self.do(Speak(player_id=self.state.next_speaker_id))
        for pid in self.state.player_ids:
            self.do(VoteTeam(player_id=pid, approve=True))
        for pid in self.state.current_mission.team:
            self.do(VoteMission(player_id=pid, success=pid != evil))
        assert self.state.missions[0].outcome is MissionOutcome.FAIL
        return good, evil


# --- Whole games -------------------------------------------------------------


@pytest.mark.parametrize("player_count", range(5, 11))
def test_bots_alone_play_a_legal_game_to_the_end(player_count: int) -> None:
    for seed in range(4):
        game = Game(player_count, seed)
        steps = 0
        while game.state.phase is not Phase.FINISHED:
            action = game.step()
            assert action.expected_version is not None
            steps += 1
            assert steps < 700
        assert game.state.winner is not None


def test_same_seed_same_game_whatever_the_game_is_called() -> None:
    def transcript(seed: int) -> list[Action]:
        game = Game(7, seed)
        actions = []
        while game.state.phase is not Phase.FINISHED:
            actions.append(game.step())
        return actions

    assert transcript(3) == transcript(3)
    assert transcript(3) != transcript(4)


def test_every_speech_fits_the_limit_in_both_languages() -> None:
    for language in ("zh", "en"):
        game = Game(10, 2)
        spoken = 0
        while game.state.phase is not Phase.FINISHED:
            action = game.bot(game.actor(), language)
            if isinstance(action, Speak):
                spoken += 1
                assert 0 < len(action.text) <= 200
                assert "\n" not in action.text
            game.do(action)
        assert spoken > 10


def test_both_sides_win_some_games() -> None:
    """The bot is not expected to be balanced, only to make a real game of it."""
    winners = set()
    for seed in range(40):
        game = Game(5, seed)
        while game.state.phase is not Phase.FINISHED:
            game.step()
        winners.add(game.state.winner)
    assert winners == {Alignment.GOOD, Alignment.EVIL}


# --- Reading the table -----------------------------------------------------------


def test_with_no_evidence_everyone_is_equally_likely() -> None:
    game = Game(7)
    servant = id_with_role(game.state, Role.LOYAL_SERVANT)
    view = build_player_view(game.state, servant)

    odds = chance_of_evil(view, read_table(view, ()), innocent=servant)

    assert set(odds) == set(player_ids(7)) - {servant}
    assert all(value == pytest.approx(3 / 6) for value in odds.values())


def test_a_good_player_on_a_failed_pair_knows_the_other_one_did_it() -> None:
    game = Game(5)
    good, evil = game.fail_first_mission()
    view = build_player_view(game.state, good)
    table = read_table(view, public_log(game.events))

    odds = chance_of_evil(view, table, innocent=good)

    assert odds[evil] == pytest.approx(1.0)
    assert all(odds[other] < 0.5 for other in odds if other != evil)


def test_an_onlooker_suspects_both_players_of_a_failed_pair_equally() -> None:
    game = Game(5)
    good, evil = game.fail_first_mission()
    onlooker = next(
        pid
        for pid in ids_with_alignment(game.state, Alignment.GOOD)
        if pid != good and game.state.find_player(pid).role is Role.LOYAL_SERVANT  # type: ignore[union-attr]
    )
    view = build_player_view(game.state, onlooker)
    table = read_table(view, public_log(game.events))

    odds = chance_of_evil(view, table, innocent=onlooker)

    assert odds[good] == pytest.approx(odds[evil])
    assert odds[good] > 2 / 4, "more suspect than before the mission"
    assert table.reasons[good] == ["failed_mission:1"]
    assert table.suspicion[good] == table.suspicion[evil] > 0


def test_an_accusation_counts_once_however_often_it_is_repeated() -> None:
    game = Game(5)
    leader = game.state.leader_id
    assert leader is not None
    target = next(pid for pid in game.state.player_ids if pid != leader)
    for _ in range(2):
        game.do(ProposeTeam(player_id=game.state.leader_id or "", team=game.state.player_ids[:2]))
        while game.state.phase is Phase.DISCUSSION:
            speaker = game.state.next_speaker_id
            assert speaker is not None
            suspects = (target,) if speaker == leader else ()
            game.do(Speak(player_id=speaker, suspects=suspects))
        for pid in game.state.player_ids:
            game.do(VoteTeam(player_id=pid, approve=False))

    view = build_player_view(game.state, "p1")
    table = read_table(view, public_log(game.events))

    assert table.accusations == [(leader, target)]
    assert table.suspicion[target] == pytest.approx(0.25)
    assert table.reasons[target] == ["accused"]


# --- Deciding ----------------------------------------------------------------


def test_a_good_bot_keeps_the_player_it_caught_off_its_team_and_says_why() -> None:
    game = Game(5)
    good, evil = game.fail_first_mission()
    # Hand the lead around until the player who was on the failed mission has it.
    while game.state.leader_id != good:
        game.do(ProposeTeam(player_id=game.state.leader_id or "", team=game.state.player_ids[:3]))
        while game.state.phase is Phase.DISCUSSION:
            game.do(Speak(player_id=game.state.next_speaker_id or ""))
        for pid in game.state.player_ids:
            game.do(VoteTeam(player_id=pid, approve=False))
        assert game.state.phase is Phase.TEAM_PROPOSAL

    proposal = game.bot(good)
    assert isinstance(proposal, ProposeTeam)
    assert good in proposal.team and evil not in proposal.team

    # Someone else proposes the culprit: the bot objects out loud, then votes that way.
    game2 = Game(5)
    good, evil = game2.fail_first_mission()
    leader = game2.state.leader_id
    assert leader is not None
    third = next(pid for pid in game2.state.player_ids if pid not in (good, evil, leader))
    team = tuple(dict.fromkeys((leader, evil, third, good)))[:3]
    if evil not in team:
        team = (evil, *team[:2])
    game2.do(ProposeTeam(player_id=leader, team=team))
    while game2.state.next_speaker_id != good:
        game2.do(Speak(player_id=game2.state.next_speaker_id or ""))
    speech = game2.bot(good)
    assert isinstance(speech, Speak)
    if good != leader:
        assert evil in speech.suspects
        assert NAMES[evil] in speech.text
        assert "failed mission 1" in speech.text
    game2.do(speech)
    while game2.state.phase is Phase.DISCUSSION:
        game2.do(Speak(player_id=game2.state.next_speaker_id or ""))
    vote = game2.bot(good)
    assert isinstance(vote, VoteTeam)
    assert vote.approve is (good == leader)


def test_good_bots_let_the_last_proposal_through() -> None:
    game = Game(5)
    good, evil = game.fail_first_mission()
    while game.state.rejected_proposals < game.state.ruleset.max_rejected_proposals - 1:
        game.do(ProposeTeam(player_id=game.state.leader_id or "", team=game.state.player_ids[:3]))
        while game.state.phase is Phase.DISCUSSION:
            game.do(Speak(player_id=game.state.next_speaker_id or ""))
        for pid in game.state.player_ids:
            game.do(VoteTeam(player_id=pid, approve=False))
    leader = game.state.leader_id or ""
    others = [pid for pid in game.state.player_ids if pid not in (evil, good)]
    game.do(ProposeTeam(player_id=leader, team=(evil, good, others[0])))
    while game.state.phase is Phase.DISCUSSION:
        game.do(Speak(player_id=game.state.next_speaker_id or ""))

    vote = game.bot(good)

    assert isinstance(vote, VoteTeam) and vote.approve, "a fifth rejection loses the game"


def test_good_bots_always_play_success_and_evil_ends_the_game_when_it_can() -> None:
    game = Game(5, seed=2)
    cards: dict[Alignment, set[bool]] = {Alignment.GOOD: set(), Alignment.EVIL: set()}
    decisive: list[bool] = []
    for seed in range(30):
        game = Game(5, seed)
        while game.state.phase is not Phase.FINISHED:
            actor = game.actor()
            action = game.bot(actor)
            if isinstance(action, VoteMission):
                role = game.state.find_player(actor).role  # type: ignore[union-attr]
                assert role is not None
                cards[role.alignment].add(action.success)
                if role.alignment is Alignment.EVIL and game.state.failed_missions == 2:
                    decisive.append(action.success)
            game.do(action)

    assert cards[Alignment.GOOD] == {True}
    assert cards[Alignment.EVIL] == {True, False}, "evil sometimes hides, sometimes fails"
    assert decisive and not any(decisive), "with two fails already, the third is played"


def test_an_evil_leader_brings_itself_and_no_more_partners_than_needed() -> None:
    for seed in range(20):
        game = Game(7, seed)
        evil = set(ids_with_alignment(game.state, Alignment.EVIL))
        leader = game.state.leader_id or ""
        if leader not in evil:
            continue
        proposal = game.bot(leader)
        assert isinstance(proposal, ProposeTeam)
        assert leader in proposal.team
        assert len(evil & set(proposal.team)) == 1
        return
    raise AssertionError("no seed gave evil the first lead")


def test_an_evil_bot_never_accuses_its_partners() -> None:
    for seed in range(15):
        game = Game(7, seed)
        evil = set(ids_with_alignment(game.state, Alignment.EVIL))
        while game.state.phase is not Phase.FINISHED:
            actor = game.actor()
            action = game.bot(actor)
            if isinstance(action, Speak) and actor in evil:
                assert not evil & set(action.suspects)
            game.do(action)


def test_merlin_never_names_someone_the_table_has_no_reason_to_doubt() -> None:
    """Merlin acts on what it knows but only gives reasons everyone can check."""
    for seed in range(15):
        game = Game(6, seed)
        merlin = id_with_role(game.state, Role.MERLIN)
        while game.state.phase is not Phase.FINISHED:
            actor = game.actor()
            action = game.bot(actor)
            if isinstance(action, Speak) and actor == merlin:
                view = build_player_view(game.state, merlin)
                public = read_table(view, public_log(game.events))
                for suspect in action.suspects:
                    assert public.suspicion[suspect] >= 0.5
            game.do(action)


def test_the_assassin_never_shoots_a_partner() -> None:
    shots = 0
    for seed in range(120):
        game = Game(5, seed)
        while game.state.phase not in (Phase.ASSASSINATION, Phase.FINISHED):
            game.step()
        if game.state.phase is Phase.FINISHED:
            continue
        assassin = id_with_role(game.state, Role.ASSASSIN)
        shot = game.bot(assassin)
        assert isinstance(shot, Assassinate)
        assert shot.target_id not in ids_with_alignment(game.state, Alignment.EVIL)
        shots += 1
    assert shots > 10


def test_a_bot_with_nothing_to_do_says_so() -> None:
    game = Game(5)
    idle = next(pid for pid in game.state.player_ids if pid != game.state.leader_id)

    with pytest.raises(ValueError, match="nothing to do"):
        choose_action(build_player_view(game.state, idle), random.Random(1))


def test_a_bot_does_not_start_games() -> None:
    with pytest.raises(ValueError, match="cannot perform 'start_game'"):
        choose_action(build_player_view(lobby(), "p1"), random.Random(1))
