"""Flask web interface — invoicing blueprint (issue, mark paid, adjudicate)."""

from books import create_app
from books.interfaces.web.app import create_web_app


def _app_client():
    books = create_app("sqlite://")
    return books, create_web_app(books).test_client()


def _setup(books):
    acme = books.party.register_party(name="Acme", role="customer")
    books.ledger.create_account(code="Bank", name="Bank", type="asset")
    books.ledger.create_account(code="AR", name="AR", type="asset", control=True)
    books.ledger.create_account(code="Revenue", name="Revenue", type="income")
    books.ledger.create_account(code="FX Loss", name="FX Loss", type="expense")
    return acme


def test_issue_invoice_posts_to_ledger():
    books, c = _app_client()
    acme = _setup(books)
    resp = c.post(
        "/invoicing/issue",
        data={
            "number": "1",
            "party_id": str(acme.id),
            "amount": "1000.00",
            "currency": "MYR",
            "issued_on": "2026-01-10",
            "rate": "1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert books.ledger.account_balance(code="AR").minor_units == 1000_00


def test_mark_paid_shortfall_then_adjudicate_still_owes_keeps_ar_open():
    books, c = _app_client()
    acme = _setup(books)
    c.post(
        "/invoicing/issue",
        data={
            "number": "1",
            "party_id": str(acme.id),
            "amount": "1000.00",
            "currency": "SGD",
            "issued_on": "2026-01-10",
            "rate": "3.20",
        },
    )
    c.post(
        "/invoicing/1/mark-paid",
        data={
            "paid_on": "2026-01-20",
            "banked": "3180.00",
        },
    )
    resp = c.post(
        "/invoicing/1/adjudicate",
        data={
            "outcome": "still_owes",
            "on": "2026-01-25",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert books.ledger.account_balance(code="AR").minor_units == 20_00
    assert books.ledger.account_balance(code="FX Loss").minor_units == 0


def test_unknown_invoice_mark_paid_flashes_not_500():
    books, c = _app_client()
    _setup(books)
    resp = c.post(
        "/invoicing/999/mark-paid",
        data={"paid_on": "2026-01-20"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "no invoice 999" in resp.get_data(as_text=True)


def test_issue_into_closed_period_flashes_clean_message():
    books, c = _app_client()
    acme = _setup(books)
    books.ledger.soft_close("2026-01")
    resp = c.post(
        "/invoicing/issue",
        data={
            "number": "1",
            "party_id": str(acme.id),
            "amount": "1000.00",
            "currency": "MYR",
            "issued_on": "2026-01-15",
            "rate": "1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-01" in body
    assert "closed" in body
    # PeriodClosedError is a ValueError → existing errorhandler flashes it;
    # the atomic UnitOfWork means no ghost invoice persisted.
    assert books.invoicing.list_invoices() == []
