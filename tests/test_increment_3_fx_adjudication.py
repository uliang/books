"""Thickening increment 3 — SGD/FX realized-only adjudication (ADR-0005).

Same spine, one new test, no rework. A foreign-currency invoice that
settles for less MYR than its booked carrying value is *ambiguous*
(adverse FX vs underpayment). The system guesses nothing:

- Issue SGD 1,000 at a manually-entered booking rate → AR carrying
  MYR 3,200 (functional currency, ADR-0017).
- MYR 3,180 lands; the Bank/AR posting records only what moved, so a
  MYR 20 shortfall sits *open* — never auto-resolved.
- settlement_picture surfaces both numbers for the owner.
- Owner adjudicates *settled in full*: the MYR 20 is a realized FX loss,
  recognized only at settlement (ADR-0005) via the guided-journal path
  (ADR-0006) — Invoicing publishes, Ledger posts. AR nets to zero; the
  loss lands in a dedicated P&L account.

See docs/adr/0005-multi-currency-realized-only-fx.md and the plan.
"""

from datetime import date
from decimal import Decimal

from books import create_app
from books.platform.money import Currency, Money


def test_foreign_invoice_underpaid_in_myr_is_owner_adjudicated_as_realized_fx():
    app = create_app()

    # --- Given ----------------------------------------------------------
    acme = app.party.register_party(name="Acme", role="customer")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="FX Loss", name="Realized FX Loss", type="expense")

    # SGD 1,000 booked at 3.20 → AR carrying value MYR 3,200.
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money(1000_00, Currency.SGD),
        issued_on=date(2026, 1, 10),
        rate=Decimal("3.20"),
    )
    assert app.ledger.account_balance(code="AR") == Money.myr(3200_00)

    # --- When: only MYR 3,180 lands ------------------------------------
    app.invoicing.mark_paid(
        invoice_id=inv.id,
        paid_on=date(2026, 1, 20),
        banked=Money.myr(3180_00),
    )
    # The posting records only what moved; the MYR 20 gap is left OPEN —
    # the system does not guess underpayment vs FX.
    assert app.ledger.account_balance(code="Bank") == Money.myr(3180_00)
    assert app.ledger.account_balance(code="AR") == Money.myr(20_00)

    # The system surfaces both numbers; it never auto-resolves.
    picture = app.invoicing.settlement_picture(inv.id)
    assert picture.transaction_amount == Money(1000_00, Currency.SGD)
    assert picture.carrying == Money.myr(3200_00)
    assert picture.banked == Money.myr(3180_00)
    assert picture.shortfall == Money.myr(20_00)

    # --- Then: owner adjudicates "settled in full" ---------------------
    # Realized FX loss recognized only at settlement, via the guided-
    # journal path (Invoicing publishes → Ledger posts the template).
    app.invoicing.adjudicate_settlement(
        invoice_id=inv.id,
        outcome="settled_in_full",
        on=date(2026, 1, 25),
    )
    assert app.ledger.account_balance(code="AR") == Money.myr(0)
    assert app.ledger.account_balance(code="FX Loss") == Money.myr(20_00)
