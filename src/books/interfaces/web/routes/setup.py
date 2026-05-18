"""setup_bp — landing page plus party/account prerequisites."""

from __future__ import annotations

from flask import Blueprint, render_template

setup_bp = Blueprint("setup", __name__)


@setup_bp.get("/")
def landing():
    parties: list = []
    accounts: list = []
    return render_template("landing.html", parties=parties, accounts=accounts)
