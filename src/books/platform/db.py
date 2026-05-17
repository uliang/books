"""One SQLite/SQLAlchemy database; one transaction per use-case command.

ADR-0013. SQLAlchemy is the data-access seam, so Postgres is a later swap.
The default in-memory URL uses a ``StaticPool`` so a single ``Database``
instance keeps one connection — and thus its schema and data — across units
of work (each use-case command opens its own unit of work).
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    """Shared declarative base. Each context owns its own tables on it
    (ADR-0013); ownership is a boundary convention, not a schema split."""


class Database:
    def __init__(self, url: str = "sqlite://") -> None:
        self._engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self._engine)

    @contextmanager
    def unit_of_work(self) -> Generator[Session]:
        session = Session(self._engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
