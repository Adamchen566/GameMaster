"""Table definitions. The Alembic migrations are the source of truth for the
real database; `tests/storage/test_migrations.py` checks the two agree.

    games  1 ── n  game_events      the event-sourced aggregate
    games  1 ── 1  rooms            the application wrapper around one game
    rooms  1 ── n  room_players     seats: names, bots, reconnect token digests
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
    UniqueConstraint("room_id", "player_id"),
    UniqueConstraint("token_hash"),
    CheckConstraint("seat >= 0", name="seat_not_negative"),
    CheckConstraint("is_bot = (token_hash IS NULL)", name="only_humans_have_tokens"),
)
