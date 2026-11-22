"""Initial schema: games, game_events, rooms, room_players.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

# JSONB on PostgreSQL, JSON elsewhere (SQLite for local use without Docker).
Json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
Timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "games",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("ruleset_id", sa.Text(), nullable=False),
        sa.Column("host_id", sa.Text(), nullable=False),
        sa.Column("player_ids", Json, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("winner", sa.Text(), nullable=True),
        sa.Column("win_reason", sa.Text(), nullable=True),
        sa.Column("created_at", Timestamp, nullable=False),
        sa.Column("finished_at", Timestamp, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_games"),
        sa.CheckConstraint("version >= 0", name=op.f("ck_games_version_not_negative")),
        sa.CheckConstraint(
            "(winner IS NULL) = (finished_at IS NULL) AND (winner IS NULL) = (win_reason IS NULL)",
            name=op.f("ck_games_finished_fields_together"),
        ),
    )
    op.create_table(
        "game_events",
        sa.Column("game_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", Json, nullable=False),
        sa.Column("created_at", Timestamp, nullable=False),
        # The primary key is also the "(game_id, version) is unique" guarantee:
        # two writers can never both store event N of the same game.
        sa.PrimaryKeyConstraint("game_id", "version", name="pk_game_events"),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"], name="fk_game_events_game_id_games", ondelete="CASCADE"
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_game_events_version_positive")),
    )
    op.create_table(
        "rooms",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("game_id", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("created_at", Timestamp, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_rooms"),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"], name="fk_rooms_game_id_games", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("game_id", name="uq_rooms_game_id"),
    )
    op.create_index("ix_rooms_code", "rooms", ["code"])
    op.create_table(
        "room_players",
        sa.Column("room_id", sa.Text(), nullable=False),
        sa.Column("seat", sa.SmallInteger(), nullable=False),
        sa.Column("player_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_bot", sa.Boolean(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("room_id", "seat", name="pk_room_players"),
        # A player row cannot exist without, or outlive, its room.
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], name="fk_room_players_room_id_rooms", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("room_id", "player_id", name="uq_room_players_room_id_player_id"),
        sa.UniqueConstraint("token_hash", name="uq_room_players_token_hash"),
        sa.CheckConstraint("seat >= 0", name=op.f("ck_room_players_seat_not_negative")),
        sa.CheckConstraint(
            "is_bot = (token_hash IS NULL)", name=op.f("ck_room_players_only_humans_have_tokens")
        ),
    )


def downgrade() -> None:
    op.drop_table("room_players")
    op.drop_index("ix_rooms_code", table_name="rooms")
    op.drop_table("rooms")
    op.drop_table("game_events")
    op.drop_table("games")
