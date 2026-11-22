"""Deterministic Avalon rules engine.

This package is pure: it imports only the standard library and itself, never
FastAPI, a database driver or a model SDK. Everything else talks to it through
`new_game`, `apply_action` and `replay`.
"""

from app.game.engine import apply_action, evolve, new_game, replay
from app.game.errors import ErrorCode, RuleViolation

__all__ = ["ErrorCode", "RuleViolation", "apply_action", "evolve", "new_game", "replay"]
