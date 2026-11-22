from dataclasses import FrozenInstanceError, replace

import pytest

from app.game.actions import Action, Assassinate, ProposeTeam, StartGame, VoteMission, VoteTeam
from app.game.engine import apply_action, evolve, new_game
from app.game.errors import ErrorCode, RuleViolation
from app.game.events import (
    AssassinationStarted,
    GameFinished,
    GameStarted,
    MissionCompleted,
    MissionStarted,
    TeamApproved,
    TeamRejected,
)
from app.game.rulesets import OFFICIAL, Alignment, PlayerCountRules, Role, RuleSet
from app.game.state import GameState, MissionOutcome, Phase, WinReason
from tests.game.invariants import check_invariants
from tests.game.scenarios import (
    act,
    approve_team,
    complete_mission,
    complete_missions,
    default_team,
    id_with_role,
    ids_with_alignment,
    leader_id,
    lobby,
    play_mission_cards,
    propose,
    reject_team,
    started,
    team_with_evil,
    vote_team,
)

SUCCESS = MissionOutcome.SUCCESS
FAIL = MissionOutcome.FAIL


def violation(state: GameState, action: Action) -> ErrorCode:
    with pytest.raises(RuleViolation) as error:
        apply_action(state, action)
    return error.value.code


def someone_else(state: GameState, *excluded: str) -> str:
    return next(player_id for player_id in state.player_ids if player_id not in excluded)


# --- Lobby -------------------------------------------------------------------


def test_new_game_seats_players_in_order_in_the_lobby() -> None:
    state = new_game(game_id="g", ruleset=OFFICIAL, player_ids=["ann", "bob", "cy"], host_id="bob")

    assert state.phase is Phase.LOBBY
    assert state.version == 0
    assert state.host_id == "bob"
    assert [(player.id, player.seat, player.role) for player in state.players] == [
        ("ann", 0, None),
        ("bob", 1, None),
        ("cy", 2, None),
    ]
    check_invariants(state)


def test_new_game_rejects_duplicate_players() -> None:
    with pytest.raises(RuleViolation) as error:
        new_game(game_id="g", ruleset=OFFICIAL, player_ids=["ann", "ann"], host_id="ann")

    assert error.value.code is ErrorCode.DUPLICATE_PLAYER


def test_new_game_rejects_a_host_who_is_not_seated() -> None:
    with pytest.raises(RuleViolation) as error:
        new_game(game_id="g", ruleset=OFFICIAL, player_ids=["ann", "bob"], host_id="cy")

    assert error.value.code is ErrorCode.UNKNOWN_PLAYER


# --- Starting ----------------------------------------------------------------


def test_only_the_host_can_start_the_game() -> None:
    state = lobby()

    assert violation(state, StartGame(player_id="p2", seed=1)) is ErrorCode.NOT_HOST


@pytest.mark.parametrize("player_count", [1, 4, 11])
def test_game_cannot_start_with_an_unsupported_player_count(player_count: int) -> None:
    state = lobby(player_count)

    code = violation(state, StartGame(player_id=state.host_id, seed=1))

    assert code is ErrorCode.INVALID_PLAYER_COUNT


def test_game_cannot_be_started_twice() -> None:
    state = started()

    assert violation(state, StartGame(player_id=state.host_id, seed=2)) is ErrorCode.WRONG_PHASE


def test_someone_outside_the_game_cannot_act() -> None:
    assert violation(lobby(), StartGame(player_id="ghost", seed=1)) is ErrorCode.UNKNOWN_PLAYER


def test_action_made_for_an_older_version_is_rejected() -> None:
    state = started()
    stale = ProposeTeam(
        player_id=leader_id(state), team=default_team(state), expected_version=state.version - 1
    )

    assert violation(state, stale) is ErrorCode.STALE_VERSION


def test_action_made_for_the_current_version_is_accepted() -> None:
    state = started()
    current = ProposeTeam(
        player_id=leader_id(state), team=default_team(state), expected_version=state.version
    )

    assert act(state, current).phase is Phase.TEAM_VOTE


@pytest.mark.parametrize("player_count", range(5, 11))
def test_start_deals_the_role_deck_and_sets_up_the_missions(player_count: int) -> None:
    state = lobby(player_count)
    rules = OFFICIAL.for_players(player_count)

    state, events = apply_action(state, StartGame(player_id=state.host_id, seed=7))

    assert [type(event) for event in events] == [GameStarted, MissionStarted]
    assert state.version == 2
    assert state.phase is Phase.TEAM_PROPOSAL
    assert sorted(player.role for player in state.players) == sorted(rules.roles)
    assert len(ids_with_alignment(state, Alignment.GOOD)) == rules.good_count
    assert len(ids_with_alignment(state, Alignment.EVIL)) == rules.evil_count
    assert state.leader_id in state.player_ids
    assert [mission.number for mission in state.missions] == [1, 2, 3, 4, 5]
    assert tuple(mission.team_size for mission in state.missions) == rules.team_sizes
    assert tuple(mission.fails_required for mission in state.missions) == rules.fail_thresholds
    assert state.current_mission.number == 1
    assert state.proposal_number == 1
    check_invariants(state)


def test_the_same_seed_deals_the_same_game() -> None:
    assert started(seed=42) == started(seed=42)


def test_different_seeds_deal_different_games() -> None:
    deals = {tuple(player.role for player in started(7, seed).players) for seed in range(20)}
    leaders = {started(7, seed).leader_id for seed in range(20)}

    assert len(deals) > 1
    assert len(leaders) > 1


# --- Proposing a team --------------------------------------------------------


def test_only_the_leader_can_propose_a_team() -> None:
    state = started()
    not_leader = someone_else(state, leader_id(state))

    code = violation(state, ProposeTeam(player_id=not_leader, team=default_team(state)))

    assert code is ErrorCode.NOT_LEADER


@pytest.mark.parametrize("size_change", [-1, 1])
def test_team_must_have_exactly_the_mission_size(size_change: int) -> None:
    state = started()
    team = state.player_ids[: state.current_mission.team_size + size_change]

    code = violation(state, ProposeTeam(player_id=leader_id(state), team=team))

    assert code is ErrorCode.WRONG_TEAM_SIZE


def test_team_cannot_list_the_same_player_twice() -> None:
    state = started()

    code = violation(state, ProposeTeam(player_id=leader_id(state), team=("p1", "p1")))

    assert code is ErrorCode.DUPLICATE_TEAM_MEMBER


def test_team_cannot_include_someone_outside_the_game() -> None:
    state = started()

    code = violation(state, ProposeTeam(player_id=leader_id(state), team=("p1", "ghost")))

    assert code is ErrorCode.UNKNOWN_TEAM_MEMBER


def test_team_cannot_be_proposed_while_a_vote_is_open() -> None:
    state = propose(started())

    code = violation(state, ProposeTeam(player_id=leader_id(state), team=default_team(state)))

    assert code is ErrorCode.WRONG_PHASE


def test_proposal_opens_the_team_vote_and_keeps_the_team_in_seat_order() -> None:
    state = propose(started(), team=("p4", "p2"))

    assert state.phase is Phase.TEAM_VOTE
    assert state.proposed_team == ("p2", "p4")
    check_invariants(state)


# --- Voting on a team --------------------------------------------------------


def test_player_cannot_vote_on_a_team_twice() -> None:
    state = act(propose(started()), VoteTeam(player_id="p1", approve=True))

    assert violation(state, VoteTeam(player_id="p1", approve=False)) is ErrorCode.ALREADY_VOTED


def test_team_vote_needs_a_proposal_first() -> None:
    assert violation(started(), VoteTeam(player_id="p1", approve=True)) is ErrorCode.WRONG_PHASE


def test_votes_stay_open_until_everyone_has_voted() -> None:
    state = propose(started())

    for player_id in state.player_ids[:-1]:
        state = act(state, VoteTeam(player_id=player_id, approve=True))

    assert state.phase is Phase.TEAM_VOTE
    assert len(state.team_votes) == 4
    check_invariants(state)


def test_majority_approval_sends_the_team_on_the_mission() -> None:
    state = propose(started(), team=("p1", "p2"))
    for player_id, approve in zip(state.player_ids, [True, True, True, False, False], strict=True):
        state, events = apply_action(state, VoteTeam(player_id=player_id, approve=approve))

    assert state.phase is Phase.MISSION_VOTE
    assert state.current_mission.team == ("p1", "p2")
    assert state.team_votes == ()
    assert events[-1] == TeamApproved(
        mission_number=1,
        proposal_number=1,
        approvals=("p1", "p2", "p3"),
        rejections=("p4", "p5"),
    )
    check_invariants(state)


def test_tied_vote_rejects_the_team() -> None:
    state = propose(started(6))
    for player_id, approve in zip(state.player_ids, [True, True, True, False, False, False]):
        state, events = apply_action(state, VoteTeam(player_id=player_id, approve=approve))

    assert isinstance(events[-1], TeamRejected)
    assert state.phase is Phase.TEAM_PROPOSAL


def test_rejection_passes_the_leader_to_the_next_seat_around_the_table() -> None:
    state = started()
    seats = {player.id: player.seat for player in state.players}
    leader_seats = [seats[leader_id(state)]]

    for expected_rejections in range(1, 5):
        state = reject_team(state)
        leader_seats.append(seats[leader_id(state)])

        assert state.phase is Phase.TEAM_PROPOSAL
        assert state.rejected_proposals == expected_rejections
        assert state.proposal_number == expected_rejections + 1
        assert state.proposed_team == ()
        assert state.team_votes == ()
        check_invariants(state)

    first = leader_seats[0]
    assert leader_seats == [(first + step) % 5 for step in range(5)]


def test_five_rejected_proposals_in_a_row_hand_evil_the_win() -> None:
    state = started()
    for _ in range(4):
        state = reject_team(state)
    state = propose(state)
    for player_id in state.player_ids:
        state, events = apply_action(state, VoteTeam(player_id=player_id, approve=False))

    assert events[-1] == GameFinished(winner=Alignment.EVIL, reason=WinReason.PROPOSALS_REJECTED)
    assert state.phase is Phase.FINISHED
    assert state.winner is Alignment.EVIL
    assert state.win_reason is WinReason.PROPOSALS_REJECTED
    check_invariants(state)


def test_rejection_count_starts_over_for_the_next_mission() -> None:
    state = reject_team(reject_team(started()))

    state = complete_mission(state, SUCCESS)

    assert state.current_mission.number == 2
    assert state.rejected_proposals == 0


# --- Playing a mission -------------------------------------------------------


def test_player_off_the_team_cannot_play_a_mission_card() -> None:
    state = approve_team(started(), team=("p1", "p2"))

    assert violation(state, VoteMission(player_id="p3", success=True)) is ErrorCode.NOT_ON_TEAM


def test_team_member_cannot_play_two_mission_cards() -> None:
    state = approve_team(started(), team=("p1", "p2"))
    state = act(state, VoteMission(player_id="p1", success=True))

    assert violation(state, VoteMission(player_id="p1", success=True)) is ErrorCode.ALREADY_VOTED


def test_good_player_cannot_play_a_fail_card() -> None:
    state = started()
    good = ids_with_alignment(state, Alignment.GOOD)[:2]
    state = approve_team(state, team=good)

    code = violation(state, VoteMission(player_id=good[0], success=False))

    assert code is ErrorCode.GOOD_MUST_SUCCEED


def test_mission_card_cannot_be_played_before_a_team_is_approved() -> None:
    assert violation(started(), VoteMission(player_id="p1", success=True)) is ErrorCode.WRONG_PHASE


def test_evil_player_may_play_success() -> None:
    state = started()
    state = approve_team(state, team_with_evil(state, 1))

    state = play_mission_cards(state, fails=0)

    assert state.missions[0].outcome is SUCCESS
    assert state.missions[0].fail_votes == 0


def test_one_fail_card_fails_a_normal_mission() -> None:
    state = started()
    state = approve_team(state, team_with_evil(state, 1))
    for player_id in state.current_mission.team:
        is_evil = player_id in ids_with_alignment(state, Alignment.EVIL)
        state, events = apply_action(state, VoteMission(player_id=player_id, success=not is_evil))

    assert events[-2] == MissionCompleted(mission_number=1, fail_votes=1, outcome=FAIL)
    assert state.missions[0].outcome is FAIL
    assert state.failed_missions == 1
    assert state.successful_missions == 0
    assert state.mission_votes == ()
    check_invariants(state)


def test_next_mission_starts_with_the_next_leader() -> None:
    state = started()
    seats = {player.id: player.seat for player in state.players}
    first_leader_seat = seats[leader_id(state)]

    state = complete_mission(state, SUCCESS)

    assert state.phase is Phase.TEAM_PROPOSAL
    assert state.current_mission.number == 2
    assert seats[leader_id(state)] == (first_leader_seat + 1) % 5
    check_invariants(state)


def test_fourth_mission_with_seven_players_survives_a_single_fail() -> None:
    state = complete_missions(started(7), SUCCESS, FAIL, SUCCESS)
    assert state.current_mission.fails_required == 2

    state = approve_team(state, team_with_evil(state, 1))
    state = play_mission_cards(state, fails=1)

    assert state.missions[3].outcome is SUCCESS
    assert state.missions[3].fail_votes == 1


def test_fourth_mission_with_seven_players_fails_on_two_fails() -> None:
    state = complete_missions(started(7), SUCCESS, FAIL, SUCCESS)

    state = complete_mission(state, FAIL)

    assert state.missions[3].outcome is FAIL
    assert state.missions[3].fail_votes == 2
    assert state.current_mission.number == 5


def test_third_successful_mission_starts_the_assassination() -> None:
    state = complete_missions(started(), SUCCESS, SUCCESS)
    state = approve_team(state)
    for player_id in state.current_mission.team:
        state, events = apply_action(state, VoteMission(player_id=player_id, success=True))

    assert events[-1] == AssassinationStarted(assassin_id=id_with_role(state, Role.ASSASSIN))
    assert state.phase is Phase.ASSASSINATION
    assert state.successful_missions == 3
    assert state.winner is None
    check_invariants(state)


def test_third_failed_mission_wins_the_game_for_evil() -> None:
    state = complete_missions(started(), FAIL, SUCCESS, FAIL, FAIL)

    assert state.phase is Phase.FINISHED
    assert state.failed_missions == 3
    assert state.winner is Alignment.EVIL
    assert state.win_reason is WinReason.MISSIONS_FAILED
    check_invariants(state)


# --- Assassination -----------------------------------------------------------


def awaiting_assassination(player_count: int = 5) -> GameState:
    return complete_missions(started(player_count), SUCCESS, SUCCESS, SUCCESS)


def test_only_the_assassin_can_name_a_target() -> None:
    state = awaiting_assassination()
    merlin = id_with_role(state, Role.MERLIN)
    assassin = id_with_role(state, Role.ASSASSIN)

    code = violation(state, Assassinate(player_id=merlin, target_id=assassin))

    assert code is ErrorCode.NOT_ASSASSIN


@pytest.mark.parametrize("target", ["self", "ghost"])
def test_assassin_must_target_another_player(target: str) -> None:
    state = awaiting_assassination()
    assassin = id_with_role(state, Role.ASSASSIN)
    target_id = assassin if target == "self" else "ghost"

    code = violation(state, Assassinate(player_id=assassin, target_id=target_id))

    assert code is ErrorCode.INVALID_TARGET


def test_assassination_cannot_happen_before_three_successes() -> None:
    state = started()
    assassin = id_with_role(state, Role.ASSASSIN)
    merlin = id_with_role(state, Role.MERLIN)

    code = violation(state, Assassinate(player_id=assassin, target_id=merlin))

    assert code is ErrorCode.WRONG_PHASE


def test_killing_merlin_steals_the_win_for_evil() -> None:
    state = awaiting_assassination()
    assassin = id_with_role(state, Role.ASSASSIN)
    merlin = id_with_role(state, Role.MERLIN)

    state = act(state, Assassinate(player_id=assassin, target_id=merlin))

    assert state.phase is Phase.FINISHED
    assert state.assassination_target_id == merlin
    assert state.winner is Alignment.EVIL
    assert state.win_reason is WinReason.MERLIN_ASSASSINATED
    check_invariants(state)


def test_missing_merlin_keeps_the_win_for_good() -> None:
    state = awaiting_assassination()
    assassin = id_with_role(state, Role.ASSASSIN)
    servant = id_with_role(state, Role.LOYAL_SERVANT)

    state = act(state, Assassinate(player_id=assassin, target_id=servant))

    assert state.phase is Phase.FINISHED
    assert state.winner is Alignment.GOOD
    assert state.win_reason is WinReason.MERLIN_SURVIVED
    check_invariants(state)


# --- After the game ----------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        StartGame(player_id="p1", seed=1),
        ProposeTeam(player_id="p1", team=("p1", "p2")),
        VoteTeam(player_id="p1", approve=True),
        VoteMission(player_id="p1", success=True),
        Assassinate(player_id="p1", target_id="p2"),
    ],
)
def test_finished_game_accepts_no_more_actions(action: Action) -> None:
    state = complete_missions(started(), FAIL, FAIL, FAIL)
    assert state.phase is Phase.FINISHED

    assert violation(state, action) is ErrorCode.WRONG_PHASE


# --- Rules come from the rule set, not from constants -----------------------


def test_good_wins_outright_when_the_rule_set_has_no_assassination() -> None:
    ruleset = replace(OFFICIAL, id="no-assassin", official=False, assassination_enabled=False)

    state = complete_missions(started(ruleset=ruleset), SUCCESS, SUCCESS, SUCCESS)

    assert state.phase is Phase.FINISHED
    assert state.winner is Alignment.GOOD
    assert state.win_reason is WinReason.MISSIONS_SUCCEEDED
    check_invariants(state)


SHORT_GAME = RuleSet(
    id="short",
    name="Short test game",
    official=False,
    source="test",
    tables={
        5: PlayerCountRules(
            good_count=3,
            evil_count=2,
            team_sizes=(2, 2, 2),
            fail_thresholds=(1, 1, 1),
            roles=OFFICIAL.tables[5].roles,
        )
    },
    missions_to_win=2,
    max_rejected_proposals=2,
)


def test_missions_needed_to_win_come_from_the_rule_set() -> None:
    state = complete_missions(started(ruleset=SHORT_GAME), SUCCESS, SUCCESS)

    assert len(state.missions) == 3
    assert state.phase is Phase.ASSASSINATION
    check_invariants(state)


def test_rejection_limit_comes_from_the_rule_set() -> None:
    state = reject_team(reject_team(started(ruleset=SHORT_GAME)))

    assert state.win_reason is WinReason.PROPOSALS_REJECTED
    check_invariants(state)


# --- Purity ------------------------------------------------------------------


def test_applying_an_action_leaves_the_previous_state_untouched() -> None:
    before = started(seed=3)
    snapshot = started(seed=3)

    after = vote_team(propose(before), approve=True)

    assert after != before
    assert before == snapshot


def test_state_cannot_be_modified_in_place() -> None:
    state = started()

    with pytest.raises(FrozenInstanceError):
        state.phase = Phase.FINISHED  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        state.players[0].role = Role.MERLIN  # type: ignore[misc]


def test_rejected_action_produces_no_state_and_no_events() -> None:
    state = started()

    with pytest.raises(RuleViolation) as error:
        apply_action(state, VoteMission(player_id="p1", success=True))

    assert error.value.message == str(error.value)
    assert state == started()


def test_unknown_action_object_is_a_programming_error() -> None:
    with pytest.raises(TypeError, match="Unsupported action type"):
        apply_action(started(), object())  # type: ignore[arg-type]


def test_unknown_event_object_is_a_programming_error() -> None:
    with pytest.raises(TypeError, match="Unsupported event type"):
        evolve(started(), object())  # type: ignore[arg-type]
