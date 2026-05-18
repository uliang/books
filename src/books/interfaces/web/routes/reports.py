"""reports_bp — on-demand reconciliation report (ADR-0016)."""

from __future__ import annotations

from flask import Blueprint, render_template

from books.interfaces.web.app import current_books

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


@reports_bp.get("/reconciliation/<account>/<period>")
def reconciliation(account: str, period: str):
    report = current_books().reporting.reconciliation_report(account, period)
    return render_template(
        "recon_report.html", account=account, period=period, report=report
    )
