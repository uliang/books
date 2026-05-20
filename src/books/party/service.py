"""Party application API (ADR-0013). Generic context: master data only.

A Party is referenced elsewhere by ``PartyId`` plus a cached display name
(CONTEXT) — there is no shared kernel.
"""

from __future__ import annotations

from dataclasses import dataclass

from books.party.persistence.repository import PartyRepository
from books.platform.db import Database


@dataclass(frozen=True, slots=True)
class Party:
    id: int
    name: str


class PartyService:
    def __init__(self, db: Database) -> None:
        self._repo = PartyRepository(db)

    def register_party(self, name: str, role: str) -> Party:
        with self._repo.unit_of_work() as session:
            row = self._repo.add(session, name=name, role=role)
            return Party(id=row.id, name=row.name)

    def get(self, party_id: int) -> Party:
        with self._repo.unit_of_work() as session:
            row = self._repo.get(session, party_id)
            if row is None:
                raise LookupError(f"no party {party_id}")
            return Party(id=row.id, name=row.name)
