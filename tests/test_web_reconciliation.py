"""Flask web interface — reconciliation blueprint (import, propose, confirm)."""

from books import create_app
from books.interfaces.web.app import create_web_app


def _app_client():
    books = create_app("sqlite://")
    return books, create_web_app(books).test_client()


def test_import_then_propose_then_confirm_matches_bank_posting():
    books, c = _app_client()
    acme = books.party.register_party(name="Acme", role="customer")
    books.ledger.create_account(code="Bank", name="Bank", type="asset")
    books.ledger.create_account(code="AR", name="AR", type="asset", control=True)
    books.ledger.create_account(code="Revenue", name="Revenue", type="income")
    c.post(
        "/invoicing/issue",
        data={
            "number": "1",
            "party_id": str(acme.id),
            "amount": "1000.00",
            "currency": "MYR",
            "issued_on": "2026-01-10",
            "rate": "1",
        },
    )
    c.post("/invoicing/1/mark-paid", data={"paid_on": "2026-01-20"})

    csv = "date,amount,description\n2026-01-20,1000.00,Acme payment\n"
    resp = c.post(
        "/reconciliation/import",
        data={
            "account": "Bank",
            "period": "2026-01",
            "opening": "0.00",
            "closing": "1000.00",
            "raw": csv,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    page = c.get("/reconciliation/Bank/2026-01").get_data(as_text=True)
    assert "Confirm" in page

    proposals = books.bank_reconciliation.propose_matches("Bank", "2026-01")
    assert len(proposals) == 1
    p = proposals[0]
    c.post(
        "/reconciliation/confirm",
        data={
            "statement_line_ref": str(p.statement_line_ref),
            "ledger_posting_ref": str(p.ledger_posting_ref),
        },
    )
    report = books.reporting.reconciliation_report("Bank", "2026-01")
    assert report.reconciling_items == []


def test_non_footing_statement_flashes_not_500():
    books, c = _app_client()
    books.ledger.create_account(code="Bank", name="Bank", type="asset")
    # CSV sums to 1000.00 but closing says 999.00 -> domain ValueError.
    resp = c.post(
        "/reconciliation/import",
        data={
            "account": "Bank",
            "period": "2026-01",
            "opening": "0.00",
            "closing": "999.00",
            "raw": "date,amount,description\n2026-01-20,1000.00,Acme\n",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "does not foot" in resp.get_data(as_text=True)
