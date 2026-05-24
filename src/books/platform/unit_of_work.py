"""Command-scoped unit of work (ADR-0011/0013, amended 2026-05-24).

One use-case command = one transaction. ``UnitOfWork`` opens a single
SQLAlchemy ``Session`` and publishes it through a ``contextvar`` so the
publisher's synchronous event handlers post into the *same* session and the
whole command commits or rolls back as one. This restores ADR-0011's
"dispatch inside the same transaction" guarantee that the 2026-05-20
per-context-repository UoW change silently regressed.

This is plumbing (session/transaction lifecycle) — no domain concepts — so it
belongs in ``platform/``.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from sqlalchemy.orm import Session

from books.platform.db import Database

_active_session: ContextVar[Session | None] = ContextVar("active_session", default=None)


def current_session() -> Session:
    """The session of the active command's UnitOfWork. Raises if called
    outside one — handlers must run inside the publisher's transaction."""
    session = _active_session.get()
    if session is None:
        raise RuntimeError("no active UnitOfWork")
    return session


class UnitOfWork:
    """The command-scoped transaction: ONE session, committed exactly once,
    visible to synchronous handlers via ``current_session()``."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self.session: Session | None = None
        self._token: Token[Session | None] | None = None

    def __enter__(self) -> UnitOfWork:
        self.session = Session(self._db.engine)
        self._token = _active_session.set(self.session)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                try:
                    self.session.commit()
                except Exception:
                    self.session.rollback()
                    raise
            else:
                self.session.rollback()
        finally:
            _active_session.reset(self._token)
            self.session.close()
            self.session = None
            self._token = None
