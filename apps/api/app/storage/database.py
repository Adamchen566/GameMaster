"""Connections and transactions.

`Database.transaction()` is the unit of work: every statement run inside the
`with` block shares one transaction, which commits when the block ends and
rolls back if it raises. Nested calls join the transaction that is already
open, so a repository method can be used alone or as part of a larger unit.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.pool import ConnectionPoolEntry


def _enable_sqlite_foreign_keys(connection: DBAPIConnection, _: ConnectionPoolEntry) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str) -> Engine:
    """Create an engine for a PostgreSQL URL (or SQLite, for local use without Docker)."""
    if make_url(url).get_backend_name() == "sqlite":
        # Requests run on a thread pool, so one connection may move between threads.
        engine = create_engine(url, connect_args={"check_same_thread": False})
        # SQLite ignores foreign keys unless asked on every connection.
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
        return engine
    # pool_pre_ping: a database restart must not surface as a failed request.
    return create_engine(url, pool_pre_ping=True)


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._current: ContextVar[Connection | None] = ContextVar("connection", default=None)

    @classmethod
    def from_url(cls, url: str) -> Database:
        return cls(make_engine(url))

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        current = self._current.get()
        if current is not None:
            yield current
            return

        with self.engine.begin() as connection:
            token = self._current.set(connection)
            try:
                yield connection
            finally:
                self._current.reset(token)

    def dispose(self) -> None:
        self.engine.dispose()
