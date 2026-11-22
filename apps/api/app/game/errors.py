"""Errors raised when an action breaks the rules."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable identifiers for rule violations.

    Clients and tests match on these values, so never rename an existing one.
    """

    UNKNOWN_RULESET = "unknown_ruleset"
    DUPLICATE_PLAYER = "duplicate_player"
    UNKNOWN_PLAYER = "unknown_player"
    STALE_VERSION = "stale_version"
    WRONG_PHASE = "wrong_phase"
    NOT_HOST = "not_host"
    INVALID_PLAYER_COUNT = "invalid_player_count"
    NOT_LEADER = "not_leader"
    WRONG_TEAM_SIZE = "wrong_team_size"
    DUPLICATE_TEAM_MEMBER = "duplicate_team_member"
    UNKNOWN_TEAM_MEMBER = "unknown_team_member"
    ALREADY_VOTED = "already_voted"
    NOT_ON_TEAM = "not_on_team"
    GOOD_MUST_SUCCEED = "good_must_succeed"
    NOT_ASSASSIN = "not_assassin"
    INVALID_TARGET = "invalid_target"


class RuleViolation(Exception):
    """An action that the rules do not allow. The game state is left unchanged."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
