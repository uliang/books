"""Single blueprint wiring point. Each blueprint is its own focused
module (one workflow area) registered here."""

from __future__ import annotations

from flask import Flask


def register(flask_app: Flask) -> None:
    from books.interfaces.web.routes.setup import setup_bp

    flask_app.register_blueprint(setup_bp)
