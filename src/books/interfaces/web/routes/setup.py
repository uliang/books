"""setup_bp — landing page plus party/account prerequisites."""

from __future__ import annotations

from flask import Blueprint, render_template

setup_bp = Blueprint("setup", __name__)


@setup_bp.get("/")
def landing():
    # Empty here; Task 3 populates these from an in-process registry on the
    # Flask config (Party/Ledger expose no list-all API in tracer scope).
    parties: list = []
    accounts: list = []
    return render_template("landing.html", parties=parties, accounts=accounts)
