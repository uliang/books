"""Single blueprint wiring point. Each blueprint is its own focused
module (one workflow area) registered here."""

from __future__ import annotations

from flask import Flask


def register(flask_app: Flask) -> None:
    from books.interfaces.web.routes.invoicing import invoicing_bp
    from books.interfaces.web.routes.reconciliation import reconciliation_bp
    from books.interfaces.web.routes.setup import setup_bp

    flask_app.register_blueprint(setup_bp)
    flask_app.register_blueprint(invoicing_bp)
    flask_app.register_blueprint(reconciliation_bp)
