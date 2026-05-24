"""Command-scoped UnitOfWork (ADR-0011/0013): one session per command, shared
with synchronous handlers via a contextvar, committed exactly once."""

import pytest
from sqlalchemy import text

from books.platform.db import Database
from books.platform.unit_of_work import UnitOfWork, current_session


def test_commits_on_clean_exit_and_persists():
    db = Database()
    with UnitOfWork(db) as uow:
        uow.session.execute(text("CREATE TABLE t (n INTEGER)"))
        uow.session.execute(text("INSERT INTO t VALUES (1)"))

    with UnitOfWork(db) as uow:
        assert uow.session.execute(text("SELECT n FROM t")).scalar_one() == 1


def test_rolls_back_on_exception():
    db = Database()
    with UnitOfWork(db) as uow:
        uow.session.execute(text("CREATE TABLE t (n INTEGER)"))

    with pytest.raises(RuntimeError):  # noqa: SIM117
        with UnitOfWork(db) as uow:
            uow.session.execute(text("INSERT INTO t VALUES (99)"))
            raise RuntimeError("boom")

    with UnitOfWork(db) as uow:
        assert uow.session.execute(text("SELECT count(*) FROM t")).scalar_one() == 0


def test_current_session_is_the_active_uow_session():
    db = Database()
    with UnitOfWork(db) as uow:
        assert current_session() is uow.session


def test_current_session_outside_a_uow_raises():
    with pytest.raises(RuntimeError, match="no active UnitOfWork"):
        current_session()


def test_contextvar_resets_between_sequential_commands():
    db = Database()
    with UnitOfWork(db):
        pass
    with pytest.raises(RuntimeError, match="no active UnitOfWork"):
        current_session()
