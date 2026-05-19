"""Generic per-line analytical dimensions on journal lines (ADR-0007).

CONTEXT: "Posting / Journal Line: One leg of a balanced journal entry:
(Account, amount, Dr/Cr, dimensions). Carries per-line **dimensions**
(Party in v1; Project later)." The Posting carries a typed set of
dimensions, not a hard-coded party_id column — so adding Project later is
*data*, not schema (ADR-0007's whole point; the fixed-column alternative
was the rejected design).

This proves the generic API end-to-end via the existing invoice/payment
spine: the Party dimension rides on AR legs (only) and is read back
through the generic `dimensions` dict. P&L (Revenue) and Bank legs have
no Party, exposed as empty dimensions. Backward-compat `party_name`
remains as a derived convenience.
"""

from datetime import date

from books import create_app
from books.platform.money import Money


def test_postings_expose_party_via_generic_dimensions_dict():
    app = create_app()

    acme = app.party.register_party(name="Acme", role="customer")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")

    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 1, 10),
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 1, 20))

    # AR legs (Dr at issue, Cr at payment) carry the Party dimension.
    ar_postings = app.ledger.postings_for(code="AR")
    assert len(ar_postings) == 2
    for p in ar_postings:
        assert "party" in p.dimensions
        assert p.dimensions["party"].id == str(acme.id)
        assert p.dimensions["party"].name == "Acme"

    # Revenue is a P&L leg — no Party. The dimensions dict is empty, not
    # a "missing party" sentinel; querying for a type that isn't present
    # is just a dict miss.
    (rev,) = app.ledger.postings_for(code="Revenue")
    assert rev.dimensions == {}
    assert "party" not in rev.dimensions

    # Bank leg (Dr at payment) — also no Party dimension.
    (bank,) = app.ledger.postings_for(code="Bank")
    assert bank.dimensions == {}

    # Backward-compat: party_name is derived from the Party dimension and
    # remains None for legs without one. Existing callers keep working.
    assert ar_postings[0].party_name == "Acme"
    assert ar_postings[1].party_name == "Acme"
    assert rev.party_name is None
    assert bank.party_name is None
