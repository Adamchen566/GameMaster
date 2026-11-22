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


def test_migrated_database_has_the_four_tables(database: Database) -> None:
    tables = set(inspect(database.engine).get_table_names())

    assert tables == {"games", "game_events", "rooms", "room_players", "alembic_version"}


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
