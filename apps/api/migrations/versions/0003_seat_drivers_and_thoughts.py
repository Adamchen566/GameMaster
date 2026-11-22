"""A model per seat, and what each AI seat was thinking.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None

Timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    # NULL keeps the behaviour existing model seats had: the server's default model.
    op.add_column("room_players", sa.Column("agent_driver", sa.Text(), nullable=True))

    op.create_table(
        "agent_thoughts",
        sa.Column("game_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", Timestamp, nullable=False),
        sa.PrimaryKeyConstraint("game_id", "version", "player_id", name="pk_agent_thoughts"),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"], name="fk_agent_thoughts_game_id_games", ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_thoughts")
    with op.batch_alter_table("room_players") as batch:
        batch.drop_column("agent_driver")
