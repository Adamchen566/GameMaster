import json
import random
from dataclasses import asdict

import pytest

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
from app.game.errors import ErrorCode, RuleViolation
from app.game.rulesets import OFFICIAL, Alignment, PlayerCountRules, Role, RuleSet
from app.game.simulate import next_action
from app.game.state import GameState, MissionOutcome, Phase
from app.game.views import Knowledge, LegalAction, PlayerView, build_player_view, legal_actions
from tests.game.scenarios import (
    act,
    approve_team,
    complete_missions,
    id_with_role,
    ids_with_alignment,
    lobby,
    propose,
    started,
)

SUCCESS = MissionOutcome.SUCCESS
FAIL = MissionOutcome.FAIL

FULL_CAST = RuleSet(
    id="full-cast",
    name="Every special role",
    official=False,
    source="test",
    tables={
        10: PlayerCountRules(
            good_count=6,
            evil_count=4,
            team_sizes=OFFICIAL.tables[10].team_sizes,
            fail_thresholds=OFFICIAL.tables[10].fail_thresholds,
            roles=(
                Role.MERLIN,
                Role.PERCIVAL,
                *[Role.LOYAL_SERVANT] * 4,
                Role.ASSASSIN,
                Role.MORGANA,
                Role.MORDRED,
                Role.OBERON,
            ),
        )
    },
)

EVIL = Knowledge.EVIL
M_OR_M = Knowledge.MERLIN_OR_MORGANA


def view_as(state: GameState, role: Role) -> PlayerView:
    return build_player_view(state, id_with_role(state, role))


def values_in(view: PlayerView) -> set[object]:
    """Every scalar value the view would put on the wire (field names excluded)."""
    found: set[object] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        else:
            found.add(node)

    walk(json.loads(json.dumps(asdict(view))))
    return found


@pytest.mark.parametrize(
    ("viewer", "expected"),
    [
        (Role.MERLIN, {Role.ASSASSIN: EVIL, Role.MORGANA: EVIL, Role.OBERON: EVIL}),
        (Role.PERCIVAL, {Role.MERLIN: M_OR_M, Role.MORGANA: M_OR_M}),
        (Role.LOYAL_SERVANT, {}),
        (Role.ASSASSIN, {Role.MORGANA: EVIL, Role.MORDRED: EVIL}),
        (Role.MORGANA, {Role.ASSASSIN: EVIL, Role.MORDRED: EVIL}),
        (Role.MORDRED, {Role.ASSASSIN: EVIL, Role.MORGANA: EVIL}),
        (Role.OBERON, {}),
    ],
)
def test_each_role_knows_exactly_what_the_rulebook_allows(
    viewer: Role, expected: dict[Role, Knowledge]
) -> None:
    state = started(10, ruleset=FULL_CAST)
    true_roles = {player.id: player.role for player in state.players}

    view = view_as(state, viewer)

    for info in view.players:
        if info.id == view.you_id:
            assert info.role is viewer
            assert info.alignment is viewer.alignment
            assert info.seen_as is None
        else:
            assert info.role is None
            assert info.alignment is None
            assert info.seen_as == expected.get(true_roles[info.id])


def test_lobby_view_has_no_roles_and_lets_the_host_start() -> None:
    view = build_player_view(lobby(), "p1")

    assert view.phase is Phase.LOBBY
    assert all(info.role is None and info.seen_as is None for info in view.players)
    assert view.current_mission_number is None
    assert view.proposal_number is None
    assert view.legal_actions == (LegalAction(type="start_game"),)
    assert build_player_view(lobby(), "p2").legal_actions == ()


def test_host_cannot_start_until_enough_players_are_seated() -> None:
    assert legal_actions(lobby(4), "p1") == ()


def test_loyal_servant_view_never_mentions_a_secret_role() -> None:
    state = approve_team(started(7))

    view = view_as(state, Role.LOYAL_SERVANT)

    # The only role or alignment word a loyal servant may receive is their own.
    secret_words = {role.value for role in Role} | {"evil", "merlin_or_morgana"}
    assert values_in(view) & secret_words == {"loyal_servant"}
    assert "seed" not in asdict(view)


def test_merlin_sees_evil_players_but_not_which_role_they_hold() -> None:
    state = started(7)

    view = view_as(state, Role.MERLIN)

    seen_evil = {info.id for info in view.players if info.seen_as is Knowledge.EVIL}
    assert seen_evil == set(ids_with_alignment(state, Alignment.EVIL))
    assert values_in(view) & {role.value for role in Role} == {"merlin"}


def test_team_votes_are_hidden_until_everyone_has_voted() -> None:
    state = propose(started(), team=("p1", "p2"))
    state = act(state, VoteTeam(player_id="p1", approve=True))
    state = act(state, VoteTeam(player_id="p2", approve=False))

    voter = build_player_view(state, "p1")
    waiting = build_player_view(state, "p3")

    assert voter.proposed_team == ("p1", "p2")
    assert voter.team_voted == waiting.team_voted == ("p1", "p2")
    assert voter.your_team_vote is True
    assert waiting.your_team_vote is None
    assert waiting.last_team_vote is None


def test_team_vote_is_revealed_once_it_is_complete() -> None:
    state = propose(started(), team=("p1", "p2"))
    for player_id, approve in zip(state.player_ids, [True, True, False, True, False], strict=True):
        state = act(state, VoteTeam(player_id=player_id, approve=approve))

    vote = build_player_view(state, "p5").last_team_vote

    assert vote is not None
    assert vote.approved is True
    assert vote.team == ("p1", "p2")
    assert vote.approvals == ("p1", "p2", "p4")
    assert vote.rejections == ("p3", "p5")
    assert (vote.mission_number, vote.proposal_number) == (1, 1)


def test_rejected_team_vote_is_revealed_too() -> None:
    state = propose(started())
    for player_id in state.player_ids:
        state = act(state, VoteTeam(player_id=player_id, approve=False))

    vote = build_player_view(state, "p1").last_team_vote

    assert vote is not None
    assert vote.approved is False
    assert vote.rejections == state.player_ids


def test_mission_cards_are_never_shown_to_other_players() -> None:
    state = started()
    evil_id = ids_with_alignment(state, Alignment.EVIL)[0]
    good_id = ids_with_alignment(state, Alignment.GOOD)[0]
    state = approve_team(state, team=(evil_id, good_id))
    state = act(state, VoteMission(player_id=evil_id, success=False))

    played = build_player_view(state, evil_id)
    teammate = build_player_view(state, good_id)

    assert played.mission_played == teammate.mission_played == (evil_id,)
    assert played.your_mission_card is False
    assert teammate.your_mission_card is None


def test_completed_mission_shows_only_the_team_and_the_fail_count() -> None:
    state = complete_missions(started(), FAIL)

    mission = view_as(state, Role.LOYAL_SERVANT).missions[0]

    assert mission.outcome is FAIL
    assert mission.fail_votes == 1
    assert len(mission.team) == mission.team_size


def test_assassin_steps_forward_only_when_the_assassination_begins() -> None:
    before = complete_missions(started(), SUCCESS, SUCCESS)
    during = complete_missions(before, SUCCESS)

    assert view_as(before, Role.LOYAL_SERVANT).assassin_id is None
    assert view_as(during, Role.LOYAL_SERVANT).assassin_id == id_with_role(during, Role.ASSASSIN)


def test_everything_is_revealed_when_the_game_is_over() -> None:
    state = complete_missions(started(), SUCCESS, SUCCESS, SUCCESS)
    assassin = id_with_role(state, Role.ASSASSIN)
    merlin = id_with_role(state, Role.MERLIN)
    state = act(state, Assassinate(player_id=assassin, target_id=merlin))

    view = view_as(state, Role.LOYAL_SERVANT)

    assert view.phase is Phase.FINISHED
    assert view.winner is Alignment.EVIL
    assert view.assassination_target_id == merlin
    assert {info.id: info.role for info in view.players} == {
        player.id: player.role for player in state.players
    }
    assert all(info.seen_as is None for info in view.players)
    assert view.legal_actions == ()


def test_views_are_only_built_for_seated_players() -> None:
    with pytest.raises(RuleViolation) as error:
        build_player_view(started(), "ghost")
    assert error.value.code is ErrorCode.UNKNOWN_PLAYER

    with pytest.raises(RuleViolation) as error:
        legal_actions(started(), "ghost")
    assert error.value.code is ErrorCode.UNKNOWN_PLAYER


def concrete_actions(legal: LegalAction, player_id: str, rng: random.Random) -> list[Action]:
    """Every distinct action a legal-action entry stands for (one sample for teams)."""
    match legal.type:
        case "propose_team":
            assert legal.team_size is not None
            team = tuple(rng.sample(legal.targets, legal.team_size))
            return [ProposeTeam(player_id=player_id, team=team)]
        case "speak":
            suspect = rng.choice(legal.targets)
            return [
                Speak(player_id=player_id),
                Speak(player_id=player_id, text="I doubt this team.", suspects=(suspect,)),
            ]
        case "vote_team":
            return [VoteTeam(player_id=player_id, approve=choice) for choice in (True, False)]
        case "vote_mission":
            cards = (True, False) if legal.can_fail else (True,)
            return [VoteMission(player_id=player_id, success=card) for card in cards]
        case "assassinate":
            return [Assassinate(player_id=player_id, target_id=target) for target in legal.targets]
        case _:
            raise AssertionError(f"unexpected legal action {legal.type}")


def every_kind_of_action(state: GameState, player_id: str) -> list[Action]:
    other = next(pid for pid in state.player_ids if pid != player_id)
    return [
        StartGame(player_id=player_id, seed=1),
        ProposeTeam(player_id=player_id, team=state.player_ids[:2]),
        Speak(player_id=player_id),
        VoteTeam(player_id=player_id, approve=True),
        VoteMission(player_id=player_id, success=True),
        Assassinate(player_id=player_id, target_id=other),
    ]


def is_accepted(state: GameState, action: Action) -> bool:
    try:
        apply_action(state, action)
    except RuleViolation:
        return False
    return True


@pytest.mark.parametrize("player_count", range(5, 11))
def test_legal_actions_agree_with_the_engine_in_every_position(player_count: int) -> None:
    for seed in range(8):
        rng = random.Random(seed)
        state = started(player_count, seed)

        while state.phase is not Phase.FINISHED:
            for player_id in state.player_ids:
                offered = legal_actions(state, player_id)
                if not offered:
                    for action in every_kind_of_action(state, player_id):
                        assert not is_accepted(state, action)
                    continue

                (legal,) = offered
                for action in concrete_actions(legal, player_id, rng):
                    assert is_accepted(state, action)
                if legal.type == "vote_mission" and not legal.can_fail:
                    assert not is_accepted(state, VoteMission(player_id=player_id, success=False))

            state = act(state, next_action(state, rng))

        assert all(legal_actions(state, player_id) == () for player_id in state.player_ids)
