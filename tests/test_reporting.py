"""Reporting (generic) — the read model, computed on demand (ADR-0016).

The reconciliation report is a join over the owning contexts' query APIs:
invariant 3 (confirmed cash = Σ cleared bank postings, where cleared = has a
Match, ADR-0010) and invariant 4 (reconciled balance ties to statement
closing; nothing unexplained).
"""

from datetime import date

from books.bank_reconciliation.service import BankReconciliationService
from books.general_ledger.service import LedgerService
from books.invoicing.events import InvoiceIssued, PaymentRecorded
from books.platform.db import Database
from books.platform.events import EventBus
from books.platform.money import Money
from books.platform.unit_of_work import UnitOfWork
from books.reporting.service import ReportingService


def test_fully_matched_statement_ties_out_with_zero_difference():
    db = Database()
    bus = EventBus()
    ledger = LedgerService(db, bus)
    ledger.create_account(code="Bank", name="Bank", type="asset")
    ledger.create_account(code="AR", name="AR", type="asset", control=True)
    ledger.create_account(code="Revenue", name="Revenue", type="income")
    with UnitOfWork(db):
        bus.publish(InvoiceIssued(1, 42, "Acme", Money.myr(1000_00), date(2026, 1, 10)))
        bus.publish(PaymentRecorded(1, 42, Money.myr(1000_00), date(2026, 1, 15)))

    recon = BankReconciliationService(
        db, bank_postings=lambda a: ledger.postings_for(a)
    )
    recon.import_statement(
        account="Bank",
        period="2026-01",
        opening=Money.myr(0),
        closing=Money.myr(1000_00),
        raw="date,amount,description\n2026-01-15,1000.00,ACME TRANSFER\n",
        fmt="csv",
    )
    p = recon.propose_matches(account="Bank", period="2026-01")[0]
    recon.confirm_match(p.statement_line_ref, p.ledger_posting_ref)

    reporting = ReportingService(ledger=ledger, recon=recon)
    report = reporting.reconciliation_report(account="Bank", period="2026-01")

    assert report.statement_closing == Money.myr(1000_00)
    assert report.ledger_bank_balance == Money.myr(1000_00)
    assert report.confirmed_cash == Money.myr(1000_00)
    assert report.difference == Money.myr(0)
    assert report.reconciling_items == []
    assert report.unexplained_lines == []
