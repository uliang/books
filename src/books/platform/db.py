"""SQLite/SQLAlchemy engine container (ADR-0013, amended 2026-05-20).

``Database`` holds the engine and runs ``create_all``. Transactions belong
to the per-context repository (see ``platform.repository.Repository``); this
class is plumbing for the engine only — no domain concepts, no session
lifecycle. The default in-memory URL uses a ``StaticPool`` so a single
``Database`` instance keeps one connection — and thus its schema and data —
across the repositories that hold it.
"""

from __future__ import annotations

from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import DeclarativeBase


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

    @property
    def engine(self):
        return self._engine
