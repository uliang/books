"""General Ledger read: locked_periods() lists every closed period and its
kind (soft/hard), period-ordered. Backs the closings:// MCP resource.
"""

from __future__ import annotations

from books import create_app


def test_locked_periods_lists_soft_in_period_order():
    app = create_app("sqlite://")
    app.ledger.soft_close("2026-03")
    app.ledger.soft_close("2026-01")

    locks = app.ledger.locked_periods()

    assert [(lk.period, lk.kind) for lk in locks] == [
        ("2026-01", "soft"),
        ("2026-03", "soft"),
    ]
