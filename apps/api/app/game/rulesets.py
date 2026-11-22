"""Rule configurations.

The engine reads every number it needs (team sizes, fail thresholds, role
decks, win conditions) from a `RuleSet`. Supporting another player count or a
house variant means adding data here, not changing the state machine.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from app.game.errors import ErrorCode, RuleViolation


class Alignment(StrEnum):
    GOOD = "good"
    EVIL = "evil"


class Role(StrEnum):
    MERLIN = "merlin"
    PERCIVAL = "percival"
    LOYAL_SERVANT = "loyal_servant"
    ASSASSIN = "assassin"
    MORGANA = "morgana"
    MORDRED = "mordred"
    OBERON = "oberon"
    MINION = "minion"

    @property
    def alignment(self) -> Alignment:
        return Alignment.GOOD if self in _GOOD_ROLES else Alignment.EVIL


_GOOD_ROLES = frozenset({Role.MERLIN, Role.PERCIVAL, Role.LOYAL_SERVANT})


@dataclass(frozen=True, slots=True)
class PlayerCountRules:
    """Everything that depends on how many players are seated."""

    good_count: int
    evil_count: int
    team_sizes: tuple[int, ...]
    """Team size for each mission, in order."""
    fail_thresholds: tuple[int, ...]
    """Fail votes needed to fail each mission, in order."""
    roles: tuple[Role, ...]
    """The role deck that is shuffled onto the seats."""


@dataclass(frozen=True, slots=True)
class RuleSet:
    id: str
    name: str
    official: bool
    source: str
    tables: Mapping[int, PlayerCountRules]
    """Rules keyed by player count."""
    assassination_enabled: bool = True
    missions_to_win: int = 3
    max_rejected_proposals: int = 5
    """Evil wins when this many proposals in a row are rejected."""

    def __post_init__(self) -> None:
        # Freeze the mapping so a rule set can never change under a running game.
        object.__setattr__(self, "tables", MappingProxyType(dict(self.tables)))
        _validate(self)

    @property
    def min_players(self) -> int:
        return min(self.tables)

    @property
    def max_players(self) -> int:
        return max(self.tables)

    def for_players(self, player_count: int) -> PlayerCountRules:
        rules = self.tables.get(player_count)
        if rules is None:
            raise RuleViolation(
                ErrorCode.INVALID_PLAYER_COUNT,
                f"Rule set '{self.id}' supports {self.min_players}-{self.max_players} players, "
                f"got {player_count}.",
            )
        return rules


def _validate(ruleset: RuleSet) -> None:
    """Reject configurations the engine could not play to a decisive end."""
    if not ruleset.tables:
        raise ValueError(f"Rule set '{ruleset.id}' needs at least one player count.")
    if ruleset.missions_to_win < 1:
        raise ValueError(f"Rule set '{ruleset.id}': missions_to_win must be at least 1.")
    if ruleset.max_rejected_proposals < 1:
        raise ValueError(f"Rule set '{ruleset.id}': max_rejected_proposals must be at least 1.")
    if set(ruleset.tables) != set(range(ruleset.min_players, ruleset.max_players + 1)):
        raise ValueError(f"Rule set '{ruleset.id}': player counts must be contiguous.")

    # With this many missions one side always reaches missions_to_win.
    mission_count = 2 * ruleset.missions_to_win - 1

    for player_count, rules in ruleset.tables.items():
        where = f"Rule set '{ruleset.id}' for {player_count} players"

        if rules.good_count + rules.evil_count != player_count:
            raise ValueError(f"{where}: good_count + evil_count must equal the player count.")
        if len(rules.roles) != player_count:
            raise ValueError(f"{where}: the role deck must have one role per player.")

        alignments = Counter(role.alignment for role in rules.roles)
        if (
            alignments[Alignment.GOOD] != rules.good_count
            or alignments[Alignment.EVIL] != rules.evil_count
        ):
            raise ValueError(f"{where}: the role deck does not match good_count/evil_count.")

        if len(rules.team_sizes) != mission_count or len(rules.fail_thresholds) != mission_count:
            raise ValueError(f"{where}: expected exactly {mission_count} missions.")

        for team_size, fail_threshold in zip(rules.team_sizes, rules.fail_thresholds, strict=True):
            if not 1 <= team_size <= player_count:
                raise ValueError(f"{where}: team size {team_size} is out of range.")
            if not 1 <= fail_threshold <= min(team_size, rules.evil_count):
                raise ValueError(f"{where}: fail threshold {fail_threshold} can never be met.")

        if ruleset.assassination_enabled and (
            rules.roles.count(Role.MERLIN) != 1 or rules.roles.count(Role.ASSASSIN) != 1
        ):
            raise ValueError(f"{where}: assassination needs exactly one Merlin and one Assassin.")


def _base_deck(good_count: int, evil_count: int) -> tuple[Role, ...]:
    """Merlin and the Assassin plus plain servants and minions."""
    return (
        Role.MERLIN,
        *[Role.LOYAL_SERVANT] * (good_count - 1),
        Role.ASSASSIN,
        *[Role.MINION] * (evil_count - 1),
    )


def _official(
    good_count: int,
    evil_count: int,
    team_sizes: tuple[int, ...],
    fail_thresholds: tuple[int, ...],
) -> PlayerCountRules:
    return PlayerCountRules(
        good_count=good_count,
        evil_count=evil_count,
        team_sizes=team_sizes,
        fail_thresholds=fail_thresholds,
        roles=_base_deck(good_count, evil_count),
    )


_ONE_FAIL = (1, 1, 1, 1, 1)
_FOURTH_NEEDS_TWO = (1, 1, 1, 2, 1)

OFFICIAL = RuleSet(
    id="official",
    name="The Resistance: Avalon, 5-10 players",
    official=True,
    source=(
        "The Resistance: Avalon rulebook (Indie Boards & Cards, 2012): "
        "player-count table, quest team sizes, and the two-fail fourth quest for 7+ players."
    ),
    tables={
        5: _official(3, 2, (2, 3, 2, 3, 3), _ONE_FAIL),
        6: _official(4, 2, (2, 3, 4, 3, 4), _ONE_FAIL),
        7: _official(4, 3, (2, 3, 3, 4, 4), _FOURTH_NEEDS_TWO),
        8: _official(5, 3, (3, 4, 4, 5, 5), _FOURTH_NEEDS_TWO),
        9: _official(6, 3, (3, 4, 4, 5, 5), _FOURTH_NEEDS_TWO),
        10: _official(6, 4, (3, 4, 4, 5, 5), _FOURTH_NEEDS_TWO),
    },
)

_FOURTH_AND_FIFTH_NEED_TWO = (1, 1, 1, 2, 2)

EXTENDED = RuleSet(
    id="extended",
    name="Avalon with house rules for 11-12 players",
    official=False,
    source=(
        "Official tables for 5-10 players. 11 and 12 players are a house rule: about a third "
        "of the table is evil, teams grow by one over the ten-player table, and the later "
        "missions need two fails so a crowded team cannot be failed by one hidden player."
    ),
    tables={
        **OFFICIAL.tables,
        11: _official(7, 4, (4, 5, 4, 5, 5), _FOURTH_NEEDS_TWO),
        12: _official(7, 5, (4, 5, 5, 6, 6), _FOURTH_AND_FIFTH_NEED_TWO),
    },
)

RULESETS: Mapping[str, RuleSet] = MappingProxyType({OFFICIAL.id: OFFICIAL, EXTENDED.id: EXTENDED})


def ruleset_for(player_count: int, preferred: RuleSet = OFFICIAL) -> RuleSet:
    """`preferred` when it covers this many players, else the house rules if they do."""
    if player_count in preferred.tables or player_count not in EXTENDED.tables:
        return preferred
    return EXTENDED


def get_ruleset(ruleset_id: str) -> RuleSet:
    ruleset = RULESETS.get(ruleset_id)
    if ruleset is None:
        raise RuleViolation(ErrorCode.UNKNOWN_RULESET, f"Unknown rule set '{ruleset_id}'.")
    return ruleset
