"""Table definitions. The Alembic migrations are the source of truth for the
real database; `tests/storage/test_migrations.py` checks the two agree.

    games  1 ── n  game_events      the event-sourced aggregate
    games  1 ── 1  rooms            the application wrapper around one game
    rooms  1 ── n  room_players     seats: names, bots, reconnect token digests
    games  1 ── n  agent_states     per AI seat: private notes, how its last turn went
    games  1 ── n  agent_thoughts   what an AI seat really thought when it acted
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

# Explicit names so migrations can refer to constraints on every database.
metadata = MetaData(
    naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    }
)

# JSONB on PostgreSQL (indexable, queryable); plain JSON elsewhere.
Json = JSON().with_variant(JSONB(), "postgresql")
Timestamp = DateTime(timezone=True)

games = Table(
    "games",
    metadata,
    Column("id", Text, primary_key=True),
    Column("ruleset_id", Text, nullable=False),
    Column("host_id", Text, nullable=False),
    # Player ids in seat order: with the ruleset and host this rebuilds the lobby state.
    Column("player_ids", Json, nullable=False),
    # Number of events stored. The optimistic-concurrency check compares against this.
    Column("version", Integer, nullable=False),
    # Copied from the GameFinished event so finished games can be queried without JSON.
    Column("winner", Text),
    Column("win_reason", Text),
    Column("created_at", Timestamp, nullable=False),
    Column("finished_at", Timestamp),
    CheckConstraint("version >= 0", name="version_not_negative"),
    CheckConstraint(
        "(winner IS NULL) = (finished_at IS NULL) AND (winner IS NULL) = (win_reason IS NULL)",
        name="finished_fields_together",
    ),
)

game_events = Table(
    "game_events",
    metadata,
    Column("game_id", Text, ForeignKey("games.id", ondelete="CASCADE"), primary_key=True),
    # The game's version after this event: 1, 2, 3, ... with no gaps.
    Column("version", Integer, primary_key=True),
    Column("type", Text, nullable=False),
    Column("payload", Json, nullable=False),
    Column("created_at", Timestamp, nullable=False),
    CheckConstraint("version >= 1", name="version_positive"),
)

rooms = Table(
    "rooms",
    metadata,
    Column("id", Text, primary_key=True),
    Column("game_id", Text, ForeignKey("games.id", ondelete="CASCADE"), nullable=False),
    # Shown to people; not an identifier, so it is indexed but not unique.
    Column("code", Text, nullable=False),
    # Drives the deal and the bots. Secret until the game is over.
    Column("seed", BigInteger, nullable=False),
    Column("created_at", Timestamp, nullable=False),
    Column("gm_mode", Text, nullable=False, server_default="template"),
    Column("language", Text, nullable=False, server_default="zh"),
    UniqueConstraint("game_id"),
    Index("ix_rooms_code", "code"),
)

room_players = Table(
    "room_players",
    metadata,
    Column("room_id", Text, ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True),
    Column("seat", SmallInteger, primary_key=True),
    Column("player_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("is_bot", Boolean, nullable=False),
    # SHA-256 of the reconnect token; the token itself is never stored.
    Column("token_hash", Text),
    # Who plays a bot seat: "random" or "llm". NULL for humans.
    Column("agent", Text),
    Column("agent_style", Text),
    # Which model plays an "llm" seat; NULL is the server's default model.
    Column("agent_driver", Text),
    UniqueConstraint("room_id", "player_id"),
    UniqueConstraint("token_hash"),
    CheckConstraint("seat >= 0", name="seat_not_negative"),
    CheckConstraint("is_bot = (token_hash IS NULL)", name="only_humans_have_tokens"),
    CheckConstraint("is_bot = (agent IS NOT NULL)", name="only_bots_have_agents"),
)

agent_states = Table(
    "agent_states",
    metadata,
    Column("game_id", Text, ForeignKey("games.id", ondelete="CASCADE"), primary_key=True),
    Column("player_id", Text, primary_key=True),
    # The model's private notes to itself. Never sent to any client.
    Column("note", Text, nullable=False),
    # How the seat's most recent turn was decided: "model" or "fallback".
    Column("last_source", Text),
    Column("last_fallback_reason", Text),
    Column("updated_at", Timestamp, nullable=False),
)

agent_thoughts = Table(
    "agent_thoughts",
    metadata,
    Column("game_id", Text, ForeignKey("games.id", ondelete="CASCADE"), primary_key=True),
    # The game's version after the first event of the action the thought belongs to.
    Column("version", Integer, primary_key=True),
    Column("player_id", Text, primary_key=True),
    # Secret while the game is on: it usually gives the seat's side away.
    Column("text", Text, nullable=False),
    Column("created_at", Timestamp, nullable=False),
)
