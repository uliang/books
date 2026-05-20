"""Base Repository — the persistence touchpoint for a context (ADR-0013).

Each context's concrete repository inherits from this base, which owns the
SQLAlchemy session lifecycle and exposes ``unit_of_work()``. The service
holds only its repository (no separate ``Database`` reference) so its
relationship with persistence is mediated through one object.

This is plumbing (session/transaction lifecycle) — no domain concepts — and
so belongs in ``platform/``.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from books.platform.db import Database


class Repository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @contextmanager
    def unit_of_work(self) -> Generator[Session]:
        """One transaction per ``with``-block. Multiple repository calls
        inside the block share one transaction (ADR-0011 atomicity)."""
        session = Session(self._db.engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
