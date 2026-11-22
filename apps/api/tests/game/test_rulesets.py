from dataclasses import FrozenInstanceError, replace

import pytest

from app.game.errors import ErrorCode, RuleViolation
from app.game.rulesets import (
    EXTENDED,
    OFFICIAL,
    Alignment,
    PlayerCountRules,
    Role,
    RuleSet,
    get_ruleset,
    ruleset_for,
)

# The Resistance: Avalon rulebook, player-count and quest tables.
# player count -> (good, evil, team size per quest, fails needed per quest)
RULEBOOK = {
    5: (3, 2, (2, 3, 2, 3, 3), (1, 1, 1, 1, 1)),
    6: (4, 2, (2, 3, 4, 3, 4), (1, 1, 1, 1, 1)),
    7: (4, 3, (2, 3, 3, 4, 4), (1, 1, 1, 2, 1)),
    8: (5, 3, (3, 4, 4, 5, 5), (1, 1, 1, 2, 1)),
    9: (6, 3, (3, 4, 4, 5, 5), (1, 1, 1, 2, 1)),
    10: (6, 4, (3, 4, 4, 5, 5), (1, 1, 1, 2, 1)),
}


@pytest.mark.parametrize("player_count", sorted(RULEBOOK))
def test_official_table_matches_the_rulebook(player_count: int) -> None:
    good, evil, team_sizes, fail_thresholds = RULEBOOK[player_count]

    rules = OFFICIAL.for_players(player_count)

    assert rules.good_count == good
    assert rules.evil_count == evil
    assert rules.team_sizes == team_sizes
    assert rules.fail_thresholds == fail_thresholds


@pytest.mark.parametrize("player_count", sorted(RULEBOOK))
def test_official_deck_is_merlin_and_assassin_plus_plain_roles(player_count: int) -> None:
    rules = OFFICIAL.for_players(player_count)

    assert len(rules.roles) == player_count
    assert rules.roles.count(Role.MERLIN) == 1
    assert rules.roles.count(Role.ASSASSIN) == 1
    assert rules.roles.count(Role.LOYAL_SERVANT) == rules.good_count - 1
    assert rules.roles.count(Role.MINION) == rules.evil_count - 1


def test_official_rules_cover_five_to_ten_players() -> None:
    assert OFFICIAL.official is True
    assert OFFICIAL.min_players == 5
    assert OFFICIAL.max_players == 10
    assert OFFICIAL.assassination_enabled is True
    assert OFFICIAL.missions_to_win == 3
    assert OFFICIAL.max_rejected_proposals == 5


@pytest.mark.parametrize("player_count", [0, 4, 11, 12])
def test_unsupported_player_count_is_a_rule_violation(player_count: int) -> None:
    with pytest.raises(RuleViolation) as error:
        OFFICIAL.for_players(player_count)

    assert error.value.code is ErrorCode.INVALID_PLAYER_COUNT


def test_rule_sets_are_looked_up_by_id() -> None:
    assert get_ruleset("official") is OFFICIAL


def test_unknown_rule_set_is_a_rule_violation() -> None:
    with pytest.raises(RuleViolation) as error:
        get_ruleset("house-rules")

    assert error.value.code is ErrorCode.UNKNOWN_RULESET


@pytest.mark.parametrize(
    ("role", "alignment"),
    [
        (Role.MERLIN, Alignment.GOOD),
        (Role.PERCIVAL, Alignment.GOOD),
        (Role.LOYAL_SERVANT, Alignment.GOOD),
        (Role.ASSASSIN, Alignment.EVIL),
        (Role.MORGANA, Alignment.EVIL),
        (Role.MORDRED, Alignment.EVIL),
        (Role.OBERON, Alignment.EVIL),
        (Role.MINION, Alignment.EVIL),
    ],
)
def test_every_role_has_an_alignment(role: Role, alignment: Alignment) -> None:
    assert role.alignment is alignment


def test_rule_sets_cannot_be_changed_after_creation() -> None:
    with pytest.raises(TypeError):
        OFFICIAL.tables[11] = OFFICIAL.tables[10]  # type: ignore[index]

    with pytest.raises(FrozenInstanceError):
        OFFICIAL.missions_to_win = 1  # type: ignore[misc]


def test_a_variant_deck_with_special_roles_is_valid() -> None:
    five = replace(
        OFFICIAL.tables[5],
        roles=(Role.MERLIN, Role.PERCIVAL, Role.LOYAL_SERVANT, Role.ASSASSIN, Role.MORGANA),
    )

    variant = _ruleset(tables={5: five})

    assert variant.for_players(5).roles.count(Role.PERCIVAL) == 1


FIVE = OFFICIAL.tables[5]
ALL_LOYAL_PLUS_ASSASSIN = (
    Role.LOYAL_SERVANT,
    Role.LOYAL_SERVANT,
    Role.LOYAL_SERVANT,
    Role.ASSASSIN,
    Role.MINION,
)


def _ruleset(**overrides: object) -> RuleSet:
    settings: dict[str, object] = {
        "id": "test",
        "name": "Test rules",
        "official": False,
        "source": "test",
        "tables": {5: FIVE},
    }
    settings.update(overrides)
    return RuleSet(**settings)  # type: ignore[arg-type]


def _five(**changes: object) -> dict[int, PlayerCountRules]:
    return {5: replace(FIVE, **changes)}  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tables": {}}, "at least one player count"),
        ({"missions_to_win": 0}, "missions_to_win"),
        ({"max_rejected_proposals": 0}, "max_rejected_proposals"),
        ({"tables": {5: FIVE, 7: OFFICIAL.tables[7]}}, "contiguous"),
        ({"tables": _five(good_count=4)}, "must equal the player count"),
        ({"tables": _five(roles=FIVE.roles[:4])}, "one role per player"),
        ({"tables": _five(good_count=4, evil_count=1)}, "does not match"),
        ({"tables": _five(team_sizes=(2, 3, 2, 3))}, "exactly 5 missions"),
        ({"tables": _five(fail_thresholds=(1, 1, 1))}, "exactly 5 missions"),
        ({"tables": _five(team_sizes=(2, 3, 2, 3, 6))}, "team size 6 is out of range"),
        ({"tables": _five(team_sizes=(0, 3, 2, 3, 3))}, "team size 0 is out of range"),
        ({"tables": _five(fail_thresholds=(1, 1, 1, 3, 1))}, "fail threshold 3"),
        ({"tables": _five(fail_thresholds=(0, 1, 1, 1, 1))}, "fail threshold 0"),
        ({"tables": _five(roles=ALL_LOYAL_PLUS_ASSASSIN)}, "exactly one Merlin"),
    ],
)
def test_inconsistent_rule_sets_are_rejected(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _ruleset(**overrides)


def test_a_deck_without_merlin_is_fine_when_assassination_is_off() -> None:
    ruleset = _ruleset(tables=_five(roles=ALL_LOYAL_PLUS_ASSASSIN), assassination_enabled=False)

    assert ruleset.assassination_enabled is False


# --- house rules for 11 and 12 players --------------------------------------------------


def test_the_house_rules_keep_the_official_tables_and_add_eleven_and_twelve() -> None:
    assert EXTENDED.official is False
    assert (EXTENDED.min_players, EXTENDED.max_players) == (5, 12)
    for player_count in range(5, 11):
        assert EXTENDED.for_players(player_count) == OFFICIAL.for_players(player_count)
    assert get_ruleset("extended") is EXTENDED


@pytest.mark.parametrize(("player_count", "good", "evil"), [(11, 7, 4), (12, 7, 5)])
def test_about_a_third_of_a_big_table_is_evil(player_count: int, good: int, evil: int) -> None:
    rules = EXTENDED.for_players(player_count)

    assert (rules.good_count, rules.evil_count) == (good, evil)
    assert rules.roles.count(Role.MERLIN) == rules.roles.count(Role.ASSASSIN) == 1


def test_late_missions_of_a_big_table_need_two_fails() -> None:
    assert EXTENDED.for_players(11).fail_thresholds == (1, 1, 1, 2, 1)
    assert EXTENDED.for_players(12).fail_thresholds == (1, 1, 1, 2, 2)


@pytest.mark.parametrize(
    ("player_count", "expected"),
    [(5, "official"), (10, "official"), (11, "extended"), (12, "extended")],
)
def test_a_table_uses_the_official_rules_whenever_they_cover_it(
    player_count: int, expected: str
) -> None:
    assert ruleset_for(player_count).id == expected


def test_a_count_no_rule_set_covers_is_left_to_the_official_rules_to_reject() -> None:
    with pytest.raises(RuleViolation):
        ruleset_for(13).for_players(13)
