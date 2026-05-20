"""General Ledger (supporting) — event-fed double-entry, ADR-0011/0012/0017.

Ledger translates Invoicing's published events into balanced MYR postings;
every entry records its provenance.
"""

from datetime import date

from books.general_ledger.service import LedgerService
from books.invoicing.events import InvoiceIssued, PaymentRecorded
from books.platform.db import Database
from books.platform.events import EventBus
from books.platform.money import Money


def _ledger() -> tuple[LedgerService, EventBus]:
    bus = EventBus()
    ledger = LedgerService(Database(), bus)
    ledger.create_account(code="Bank", name="Bank", type="asset")
    ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    ledger.create_account(code="Revenue", name="Revenue", type="income")
    return ledger, bus


def test_invoice_issued_posts_dr_ar_cr_revenue_with_party_dimension():
    ledger, bus = _ledger()

    bus.publish(
        InvoiceIssued(
            invoice_number=1,
            party_id=42,
            party_name="Acme",
            amount=Money.myr(1000_00),
            issued_on=date(2026, 1, 10),
        )
    )

    assert ledger.account_balance(code="AR") == Money.myr(1000_00)
    assert ledger.account_balance(code="Revenue") == Money.myr(-1000_00)
    ar_postings = ledger.postings_for(code="AR")
    assert ar_postings[0].party_name == "Acme"


def test_payment_recorded_posts_dr_bank_cr_ar_and_bank_posting_is_uncleared():
    ledger, bus = _ledger()
    bus.publish(
        InvoiceIssued(
            invoice_number=1,
            party_id=42,
            party_name="Acme",
            amount=Money.myr(1000_00),
            issued_on=date(2026, 1, 10),
        )
    )

    bus.publish(
        PaymentRecorded(
            invoice_number=1,
            party_id=42,
            amount=Money.myr(1000_00),
            paid_on=date(2026, 1, 15),
        )
    )

    assert ledger.account_balance(code="AR") == Money.myr(0)
    assert ledger.account_balance(code="Bank") == Money.myr(1000_00)
    bank = ledger.postings_for(code="Bank")
    assert len(bank) == 1
    assert bank[0].amount == Money.myr(1000_00)
    assert bank[0].date == date(2026, 1, 15)


def test_accounts_returns_every_created_account_with_its_metadata():
    from books import create_app

    app = create_app("sqlite://")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(code="AR", name="AR", type="asset", control=True)
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")

    accounts = app.ledger.accounts()
    by_code = {a.code: a for a in accounts}
    assert set(by_code) == {"Bank", "AR", "Revenue"}
    assert by_code["Bank"].type == "asset"
    assert by_code["AR"].control is True
    assert by_code["Revenue"].type == "income"
