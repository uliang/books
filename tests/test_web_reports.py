"""Flask web interface — reports blueprint (reconciliation report)."""

from books import create_app
from books.interfaces.web.app import create_web_app


def test_report_page_renders_reconciled_state():
    books = create_app("sqlite://")
    c = create_web_app(books).test_client()
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
    c.post(
        "/reconciliation/import",
        data={
            "account": "Bank",
            "period": "2026-01",
            "opening": "0.00",
            "closing": "1000.00",
            "raw": "date,amount,description\n2026-01-20,1000.00,Acme\n",
        },
    )
    p = books.bank_reconciliation.propose_matches("Bank", "2026-01")[0]
    c.post(
        "/reconciliation/confirm",
        data={
            "statement_line_ref": str(p.statement_line_ref),
            "ledger_posting_ref": str(p.ledger_posting_ref),
        },
    )

    resp = c.get("/reports/reconciliation/Bank/2026-01")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Reconciled" in body
    assert "No reconciling items" in body
