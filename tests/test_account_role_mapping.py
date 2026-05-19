"""Configurable account role mapping.

CONTEXT (Chart of Accounts is an aggregate inside General Ledger): the
codes the GL handlers post to are not hardwired — they are a persisted
**role → code** mapping the owner can edit. Defaults match the
well-known names ("AR", "Revenue", "Bank", "FX Loss", "Write-off",
"Owner's Equity", "Due to Owner") so existing flows keep working, but
the owner can override any role to use their preferred chart (e.g.
numeric continental-style codes). Persisted, not in-process, so the
web/MCP setup surface can edit it at runtime.
"""

from datetime import date

from books import create_app
from books.platform.money import Money


def test_overriding_role_codes_routes_postings_to_the_owners_chart():
    app = create_app()

    # The owner runs a numeric chart of accounts.
    app.ledger.create_account(code="1000", name="Bank", type="asset")
    app.ledger.create_account(
        code="1200", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="4000", name="Revenue", type="income")

    app.ledger.assign_role("bank", "1000")
    app.ledger.assign_role("ar", "1200")
    app.ledger.assign_role("revenue", "4000")

    # role_code reads the override back through the query API.
    assert app.ledger.role_code("bank") == "1000"
    assert app.ledger.role_code("ar") == "1200"
    assert app.ledger.role_code("revenue") == "4000"

    # The full invoice / payment flow uses the owner's codes, end to end.
    acme = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 1, 10),
    )
    assert app.ledger.account_balance(code="1200") == Money.myr(1000_00)
    assert app.ledger.account_balance(code="4000") == Money.myr(-1000_00)

    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 1, 20))
    assert app.ledger.account_balance(code="1000") == Money.myr(1000_00)  # Bank
    assert app.ledger.account_balance(code="1200") == Money.myr(0)  # AR cleared

    # Other roles still hold their seeded defaults — only what was assigned
    # changes.
    assert app.ledger.role_code("fx_loss") == "FX Loss"
    assert app.ledger.role_code("due_to_owner") == "Due to Owner"

    # Unknown roles are rejected, not silently ignored.
    import pytest

    with pytest.raises(ValueError, match="unknown role"):
        app.ledger.assign_role("banc", "1000")  # typo
