"""books — composition root (ADR-0011/0013).

One process, one in-memory event bus, one SQLite database. Each context is
wired here and exposed only through its thin application API; interfaces
(web, MCP) will be thin adapters over this same surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from books.bank_reconciliation.service import BankReconciliationService
from books.general_ledger.service import LedgerService
from books.invoicing.service import InvoicingService
from books.party.service import PartyService
from books.platform.db import Database
from books.platform.events import EventBus
from books.reporting.service import ReportingService


@dataclass(frozen=True, slots=True)
class App:
    party: PartyService
    ledger: LedgerService
    invoicing: InvoicingService
    bank_reconciliation: BankReconciliationService
    reporting: ReportingService


def create_app(db_url: str = "sqlite://") -> App:
    # Services are imported above, so their tables are registered on the
    # shared metadata before the database creates the schema.
    db = Database(db_url)
    bus = EventBus()

    party = PartyService(db)
    ledger = LedgerService(db, bus)  # subscribes its event handlers
    invoicing = InvoicingService(db, bus, party_name=lambda pid: party.get(pid).name)
    recon = BankReconciliationService(
        db, bank_postings=lambda account: ledger.postings_for(code=account)
    )
    reporting = ReportingService(ledger=ledger, recon=recon)

    return App(
        party=party,
        ledger=ledger,
        invoicing=invoicing,
        bank_reconciliation=recon,
        reporting=reporting,
    )


def main() -> None:
    print("Hello from books!")
