"""invoicing_bp — issue invoice, list, mark paid, adjudicate FX shortfall.

The invoice id used in URLs is the value returned by issue_invoice.
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from books.interfaces.web.app import current_books
from books.interfaces.web.forms import date_from, decimal_from, money_from

invoicing_bp = Blueprint("invoicing", __name__, url_prefix="/invoicing")


@invoicing_bp.get("/issue")
def issue_form():
    return render_template("invoice_issue.html")


@invoicing_bp.post("/issue")
def issue():
    books = current_books()
    inv = books.invoicing.issue_invoice(
        number=int(request.form["number"]),
        party_id=int(request.form["party_id"]),
        amount=money_from(request.form["amount"], request.form["currency"]),
        issued_on=date_from(request.form["issued_on"]),
        rate=decimal_from(request.form["rate"]),
    )
    return redirect(url_for("invoicing.paid_form", invoice_id=inv.id))


@invoicing_bp.get("/<int:invoice_id>/mark-paid")
def paid_form(invoice_id: int):
    return render_template("invoice_paid.html", invoice_id=invoice_id, picture=None)


@invoicing_bp.post("/<int:invoice_id>/mark-paid")
def mark_paid(invoice_id: int):
    books = current_books()
    raw = (request.form.get("banked") or "").strip() or None
    banked = money_from(raw, "MYR") if raw else None
    books.invoicing.mark_paid(
        invoice_id=invoice_id,
        paid_on=date_from(request.form["paid_on"]),
        banked=banked,
    )
    picture = books.invoicing.settlement_picture(invoice_id)
    return render_template("invoice_paid.html", invoice_id=invoice_id, picture=picture)


@invoicing_bp.post("/<int:invoice_id>/adjudicate")
def adjudicate(invoice_id: int):
    current_books().invoicing.adjudicate_settlement(
        invoice_id=invoice_id,
        outcome=request.form["outcome"],
        on=date_from(request.form["on"]),
    )
    return redirect(url_for("setup.landing"))
