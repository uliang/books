"""Party application API (ADR-0013). Generic context: master data only.

A Party is referenced elsewhere by ``PartyId`` plus a cached display name
(CONTEXT) — there is no shared kernel.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from books.platform.db import Base, Database


class _Party(Base):
    __tablename__ = "party"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)


@dataclass(frozen=True, slots=True)
class Party:
    id: int
    name: str


class PartyService:
    def __init__(self, db: Database) -> None:
        self._db = db

    def register_party(self, name: str, role: str) -> Party:
        with self._db.unit_of_work() as session:
            row = _Party(name=name, role=role)
            session.add(row)
            session.flush()
            return Party(id=row.id, name=row.name)

    def get(self, party_id: int) -> Party:
        with self._db.unit_of_work() as session:
            row = session.get(_Party, party_id)
            if row is None:
                raise LookupError(f"no party {party_id}")
            return Party(id=row.id, name=row.name)
