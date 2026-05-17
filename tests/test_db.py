"""Persistence seam — ADR-0013.

One SQLite/SQLAlchemy database; a unit of work is one transaction per
use-case command: it commits on success and rolls back on error. An
in-memory database keeps its state across units of work within one
``Database`` instance.
"""

import pytest
from sqlalchemy import text

from books.platform.db import Database


def test_unit_of_work_commits_on_success_and_persists_across_uows():
    db = Database()
    with db.unit_of_work() as session:
        session.execute(text("CREATE TABLE t (n INTEGER)"))
        session.execute(text("INSERT INTO t VALUES (1)"))

    with db.unit_of_work() as session:
        assert session.execute(text("SELECT n FROM t")).scalar_one() == 1


def test_unit_of_work_rolls_back_on_error():
    db = Database()
    with db.unit_of_work() as session:
        session.execute(text("CREATE TABLE t (n INTEGER)"))

    # Kept nested deliberately: collapsing into one `with` (SIM117) mixes a
    # suppressing CM (pytest.raises) with a non-suppressing one
    # (unit_of_work), which defeats reachability analysis and obscures the
    # rollback-then-catch ordering.
    with pytest.raises(RuntimeError):  # noqa: SIM117
        with db.unit_of_work() as session:
            session.execute(text("INSERT INTO t VALUES (99)"))
            raise RuntimeError("boom")

    with db.unit_of_work() as session:
        assert session.execute(text("SELECT count(*) FROM t")).scalar_one() == 0
