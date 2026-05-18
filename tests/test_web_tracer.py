"""Web mirror of tests/test_tracer_thread_1.py — the spine of the web
increment. Drives the full slice through the Flask test client."""

from books import create_app
from books.interfaces.web.app import create_web_app


def test_web_tracer_thread_1_end_to_end():
    books = create_app("sqlite://")
    c = create_web_app(books).test_client()

    c.post("/setup/parties", data={"name": "Acme", "role": "customer"})
    for code, name, type_, ctrl in [
        ("Bank", "Bank", "asset", ""),
        ("AR", "Accounts Receivable", "asset", "1"),
        ("Revenue", "Revenue", "income", ""),
    ]:
        c.post(
            "/setup/accounts",
            data={"code": code, "name": name, "type": type_, "control": ctrl},
        )

    # party_id "1": fresh in-memory db, Acme registered above is always id 1
    c.post(
        "/invoicing/issue",
        data={
            "number": "1",
            "party_id": "1",
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
    report = books.reporting.reconciliation_report("Bank", "2026-01")
    assert report.difference.minor_units == 0
    assert report.reconciling_items == []
