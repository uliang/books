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
    """Engine container (ADR-0013, amended 2026-05-20). Transactions belong
    to the per-context repository; this class only holds the SQLAlchemy
    engine and runs ``create_all``. ``unit_of_work`` lives on
    ``platform.repository.Repository`` (the persistence touchpoint a service
    actually talks to). The legacy ``unit_of_work`` method is retained here
    transiently for contexts not yet migrated to the repository pattern; it
    is removed once every context has migrated."""

    def __init__(self, url: str = "sqlite://") -> None:
        self._engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self._engine)

    @property
    def engine(self):
        return self._engine

    @contextmanager
    def unit_of_work(self) -> Generator[Session]:
        # Transient — used only by contexts not yet on the Repository
        # pattern. Removed once the rollout completes.
        session = Session(self._engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
