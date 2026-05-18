"""reports_bp — on-demand reconciliation report (ADR-0016)."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from books.interfaces.web.app import current_books

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


@reports_bp.get("/reconciliation")
def reconciliation_redirect():
    # HTML GET forms submit query args; bounce to the canonical path-param
    # report URL so the address bar stays shareable.
    return redirect(
        url_for(
            "reports.reconciliation",
            account=request.args["account"],
            period=request.args["period"],
        )
    )


@reports_bp.get("/reconciliation/<account>/<period>")
def reconciliation(account: str, period: str):
    report = current_books().reporting.reconciliation_report(account, period)
    return render_template(
        "recon_report.html", account=account, period=period, report=report
    )
