"""Web interface composition (design: web-interface-tracer-slice).

A thin Flask adapter over the existing composition root. One App per
process, held on the Flask config; injectable so tests use in-memory.
The web layer only translates HTTP <-> service calls; domain invariants
stay in the domain (service-raised ValueError/LookupError -> flash).
"""

from __future__ import annotations

from flask import Flask, Response, current_app, flash, redirect, request

from books import App, create_app


def current_books() -> App:
    return current_app.config["BOOKS"]


def create_web_app(books_app: App | None = None) -> Flask:
    flask_app = Flask(__name__)
    flask_app.secret_key = "books-dev-not-secret"  # dev-only; no auth (v1)
    flask_app.config["BOOKS"] = books_app or create_app(db_url="sqlite:///books.db")

    from books.interfaces.web.routes import register

    register(flask_app)

    @flask_app.errorhandler(ValueError)
    @flask_app.errorhandler(LookupError)
    def _domain_error(exc: Exception) -> Response:
        flash(str(exc))
        return redirect(request.referrer or "/")

    return flask_app
