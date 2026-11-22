from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.storage.database import Database
from app.storage.schema import metadata
from tests.storage.conftest import alembic_config


def test_migrations_build_exactly_the_schema_the_code_expects(database: Database) -> None:
    with database.engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), metadata)

    assert differences == []


def test_migrated_database_has_exactly_the_expected_tables(database: Database) -> None:
    tables = set(inspect(database.engine).get_table_names())

    assert tables == {
        "games",
        "game_events",
        "rooms",
        "room_players",
        "agent_states",
        "alembic_version",
    }


def test_check_constraints_survive_the_table_rebuild(database: Database) -> None:
    """SQLite rebuilds room_players to add a constraint; the old ones must come along."""
    names = {
        check["name"] for check in inspect(database.engine).get_check_constraints("room_players")
    }

    assert names == {
        "ck_room_players_seat_not_negative",
        "ck_room_players_only_humans_have_tokens",
        "ck_room_players_only_bots_have_agents",
    }


def test_event_log_is_keyed_by_game_and_version(database: Database) -> None:
    primary_key = inspect(database.engine).get_pk_constraint("game_events")

    assert primary_key["constrained_columns"] == ["game_id", "version"]


def test_downgrade_removes_everything_and_upgrade_restores_it(url: str) -> None:
    config = alembic_config(url)

    command.downgrade(config, "base")
    database = Database.from_url(url)
    assert set(inspect(database.engine).get_table_names()) == {"alembic_version"}
    database.dispose()

    command.upgrade(config, "head")
    database = Database.from_url(url)
    assert "game_events" in inspect(database.engine).get_table_names()
    database.dispose()
