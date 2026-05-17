"""Invoicing (supporting) — sell-side capture; upstream source of AR.

Issuing publishes InvoiceIssued; marking paid (a human assertion the funds
are already in the bank, CONTEXT) publishes PaymentRecorded. Invoicing never
touches the Ledger directly.
"""

from datetime import date

from books.invoicing.events import InvoiceIssued, PaymentRecorded
from books.invoicing.service import InvoicingService
from books.platform.db import Database
from books.platform.events import EventBus
from books.platform.money import Money


def _invoicing() -> tuple[InvoicingService, list]:
    bus = EventBus()
    captured: list = []
    bus.subscribe(InvoiceIssued, captured.append)
    bus.subscribe(PaymentRecorded, captured.append)
    svc = InvoicingService(
        Database(), bus, party_name=lambda pid: "Acme" if pid == 42 else "?"
    )
    return svc, captured


def test_issue_invoice_publishes_invoice_issued_with_cached_party_name():
    svc, captured = _invoicing()

    inv = svc.issue_invoice(
        number=1,
        party_id=42,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 1, 10),
    )

    assert inv.id is not None
    assert captured == [
        InvoiceIssued(
            invoice_number=1,
            party_id=42,
            party_name="Acme",
            amount=Money.myr(1000_00),
            issued_on=date(2026, 1, 10),
        )
    ]


def test_mark_paid_publishes_payment_recorded():
    svc, captured = _invoicing()
    inv = svc.issue_invoice(
        number=1,
        party_id=42,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 1, 10),
    )
    captured.clear()

    svc.mark_paid(invoice_id=inv.id, paid_on=date(2026, 1, 15))

    assert captured == [
        PaymentRecorded(
            invoice_number=1,
            party_id=42,
            amount=Money.myr(1000_00),
            paid_on=date(2026, 1, 15),
        )
    ]
