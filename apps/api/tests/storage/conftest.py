"""Databases for storage tests.

Every SQL test runs against SQLite (always available) and against PostgreSQL
when TEST_DATABASE_URL is set. CI sets REQUIRE_POSTGRES_TESTS=1 so a missing
database fails the build instead of quietly skipping the tests that matter.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.game.repository import GameRepository, InMemoryGameRepository
from app.rooms import InMemoryRoomStore, RoomStore
from app.storage.database import Database
from app.storage.games import SqlGameRepository
from app.storage.rooms import SqlRoomStore
from app.storage.schema import metadata

API_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    # ConfigParser treats % as interpolation; a URL may contain %-escapes.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def migrate(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


def postgres_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return url
    if os.environ.get("REQUIRE_POSTGRES_TESTS") == "1":
        pytest.fail("REQUIRE_POSTGRES_TESTS=1 but TEST_DATABASE_URL is not set.")
    pytest.skip("Set TEST_DATABASE_URL to run this against PostgreSQL.")


def database_url(backend: str, tmp_path: Path) -> str:
    """Return the URL of a migrated, empty database."""
    if backend == "sqlite":
        url = f"sqlite:///{(tmp_path / 'avalon.db').as_posix()}"
        migrate(url)
        return url

    url = postgres_url()
    migrate(url)
    database = Database.from_url(url)
    with database.transaction() as connection:
        tables = ", ".join(table.name for table in metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE {tables}"))
    database.dispose()
    return url


SQL_BACKENDS = ["sqlite", "postgres"]


@pytest.fixture(params=SQL_BACKENDS)
def url(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    return database_url(request.param, tmp_path)


@pytest.fixture
def database(url: str) -> Iterator[Database]:
    database = Database.from_url(url)
    yield database
    database.dispose()


@pytest.fixture
def pg_database(tmp_path: Path) -> Iterator[Database]:
    """For tests of behaviour only PostgreSQL has (row locks, JSONB queries)."""
    database = Database.from_url(database_url("postgres", tmp_path))
    yield database
    database.dispose()


@pytest.fixture(params=["memory", *SQL_BACKENDS])
def repository(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[GameRepository]:
    if request.param == "memory":
        yield InMemoryGameRepository()
        return
    database = Database.from_url(database_url(request.param, tmp_path))
    yield SqlGameRepository(database)
    database.dispose()


@pytest.fixture(params=["memory", *SQL_BACKENDS])
def stores(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[tuple[GameRepository, RoomStore]]:
    if request.param == "memory":
        yield InMemoryGameRepository(), InMemoryRoomStore()
        return
    database = Database.from_url(database_url(request.param, tmp_path))
    yield SqlGameRepository(database), SqlRoomStore(database)
    database.dispose()
