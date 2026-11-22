"""AI seats, game master settings and per-seat agent state.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None

Timestamp = sa.DateTime(timezone=True)

# SQLite adds a constraint by rebuilding the table. Without this, the rebuild would
# run the existing constraint names through the naming convention a second time.
_KEEP_NAMES = {"ck": "%(constraint_name)s"}


def upgrade() -> None:
    # Existing rooms get the behaviour they already had: template announcements in Chinese.
    op.add_column(
        "rooms", sa.Column("gm_mode", sa.Text(), nullable=False, server_default="template")
    )
    op.add_column("rooms", sa.Column("language", sa.Text(), nullable=False, server_default="zh"))

    op.add_column("room_players", sa.Column("agent", sa.Text(), nullable=True))
    op.add_column("room_players", sa.Column("agent_style", sa.Text(), nullable=True))
    # Every bot seat so far was the random legal bot.
    op.execute("UPDATE room_players SET agent = 'random' WHERE is_bot")
    # Batch mode: SQLite can only add a constraint by rebuilding the table.
    with op.batch_alter_table("room_players", naming_convention=_KEEP_NAMES) as batch:
        # op.f(): the name is final; do not run it through the naming convention again.
        batch.create_check_constraint(
            op.f("ck_room_players_only_bots_have_agents"), "is_bot = (agent IS NOT NULL)"
        )

    op.create_table(
        "agent_states",
        sa.Column("game_id", sa.Text(), nullable=False),
        sa.Column("player_id", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("last_source", sa.Text(), nullable=True),
        sa.Column("last_fallback_reason", sa.Text(), nullable=True),
        sa.Column("updated_at", Timestamp, nullable=False),
        sa.PrimaryKeyConstraint("game_id", "player_id", name="pk_agent_states"),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"], name="fk_agent_states_game_id_games", ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_states")
    with op.batch_alter_table("room_players", naming_convention=_KEEP_NAMES) as batch:
        batch.drop_constraint(op.f("ck_room_players_only_bots_have_agents"), type_="check")
        batch.drop_column("agent_style")
        batch.drop_column("agent")
    with op.batch_alter_table("rooms") as batch:
        batch.drop_column("language")
        batch.drop_column("gm_mode")
