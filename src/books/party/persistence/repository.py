"""Party repository (ADR-0013 amended 2026-05-20). The single persistence
touchpoint for :class:`PartyService`."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from books.party.persistence.tables import _Party
from books.platform.repository import Repository


@dataclass(frozen=True, slots=True)
class PartyRow:
    id: int
    name: str
    role: str


class PartyRepository(Repository):
    def add(self, session: Session, *, name: str, role: str) -> PartyRow:
        row = _Party(name=name, role=role)
        session.add(row)
        session.flush()
        return PartyRow(id=row.id, name=row.name, role=row.role)

    def get(self, session: Session, party_id: int) -> PartyRow | None:
        row = session.get(_Party, party_id)
        if row is None:
            return None
        return PartyRow(id=row.id, name=row.name, role=row.role)
