"""Persistence seam — ADR-0013 (amended 2026-05-20).

The unit of work belongs to the repository, not the platform ``Database``
(which narrowed to an engine container). One ``with repo.unit_of_work():``
block is one transaction: commits on success, rolls back on error. The
in-memory database keeps state across units of work within one ``Database``
instance (so a downstream repo created against the same db sees prior
commits).
"""

import pytest
from sqlalchemy import text

from books.platform.db import Database
from books.platform.repository import Repository


class _Repo(Repository):
    """A throwaway concrete repository — Repository is the base class with
    the UoW machinery; subclasses only add intent-named methods."""


def test_unit_of_work_commits_on_success_and_persists_across_uows():
    repo = _Repo(Database())
    with repo.unit_of_work() as session:
        session.execute(text("CREATE TABLE t (n INTEGER)"))
        session.execute(text("INSERT INTO t VALUES (1)"))

    with repo.unit_of_work() as session:
        assert session.execute(text("SELECT n FROM t")).scalar_one() == 1


def test_unit_of_work_rolls_back_on_error():
    repo = _Repo(Database())
    with repo.unit_of_work() as session:
        session.execute(text("CREATE TABLE t (n INTEGER)"))

    # Kept nested deliberately: collapsing into one `with` (SIM117) mixes a
    # suppressing CM (pytest.raises) with a non-suppressing one
    # (unit_of_work), which defeats reachability analysis and obscures the
    # rollback-then-catch ordering.
    with pytest.raises(RuntimeError):  # noqa: SIM117
        with repo.unit_of_work() as session:
            session.execute(text("INSERT INTO t VALUES (99)"))
            raise RuntimeError("boom")

    with repo.unit_of_work() as session:
        assert session.execute(text("SELECT count(*) FROM t")).scalar_one() == 0
