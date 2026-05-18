"""reconciliation_bp — import statement (CSV), propose, confirm.

confirm_match is the sole reconciliation write (ADR-0015). The CSV is
posted as a text field for the tracer; a file upload is a later
thickening (out of slice scope).
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from books.interfaces.web.app import current_books
from books.interfaces.web.forms import money_from

reconciliation_bp = Blueprint("reconciliation", __name__, url_prefix="/reconciliation")


@reconciliation_bp.get("/import")
def import_form():
    return render_template("import_statement.html")


@reconciliation_bp.post("/import")
def import_statement():
    f = request.form
    current_books().bank_reconciliation.import_statement(
        account=f["account"],
        period=f["period"],
        opening=money_from(f["opening"]),
        closing=money_from(f["closing"]),
        raw=f["raw"],
    )
    return redirect(
        url_for("reconciliation.view", account=f["account"], period=f["period"])
    )


@reconciliation_bp.get("/<account>/<period>")
def view(account: str, period: str):
    books = current_books()
    lines = books.bank_reconciliation.statement_lines(account, period)
    proposals = books.bank_reconciliation.propose_matches(account, period)
    return render_template(
        "reconcile.html",
        account=account,
        period=period,
        lines=lines,
        proposals=proposals,
    )


@reconciliation_bp.post("/confirm")
def confirm():
    f = request.form
    current_books().bank_reconciliation.confirm_match(
        statement_line_ref=int(f["statement_line_ref"]),
        ledger_posting_ref=int(f["ledger_posting_ref"]),
    )
    return redirect(request.referrer or url_for("setup.landing"))
