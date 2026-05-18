"""setup_bp — landing page plus party/account prerequisites.

Party/Ledger have no list-all query in the tracer scope; the web layer
keeps a small in-process registry of what it created so the owner can
see current state. This is a view convenience, not domain state.
"""

from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from books.interfaces.web.app import current_books

setup_bp = Blueprint("setup", __name__, url_prefix="")


def _seen(kind: str) -> list:
    # Stored on the Flask app instance, so it is fresh per create_web_app()
    # (and thus per test_client()); not shared across app instances.
    return current_app.config.setdefault("_SEEN", {}).setdefault(kind, [])


@setup_bp.get("/")
def landing():
    return render_template(
        "landing.html", parties=_seen("parties"), accounts=_seen("accounts")
    )


@setup_bp.get("/setup/parties")
def parties_form():
    return render_template("parties.html")


@setup_bp.post("/setup/parties")
def register_party():
    party = current_books().party.register_party(
        name=request.form["name"], role=request.form["role"]
    )
    _seen("parties").append({"id": party.id, "name": party.name})
    return redirect(url_for("setup.landing"))


@setup_bp.get("/setup/accounts")
def accounts_form():
    return render_template("accounts.html")


@setup_bp.post("/setup/accounts")
def create_account():
    code = request.form["code"]
    name = request.form["name"]
    current_books().ledger.create_account(
        code=code,
        name=name,
        type=request.form["type"],
        control=bool(request.form.get("control")),
    )
    _seen("accounts").append({"code": code, "name": name})
    return redirect(url_for("setup.landing"))
