"""Invoicing resources: the agent's invoice lookup and the both-numbers
settlement picture used to adjudicate a foreign-currency shortfall.

- invoices:// — every invoice (list), so mark_paid / adjudicate have an id.
- invoices://{invoice_id}/settlement — the SettlementPicture (ADR-0005):
  transaction amount, MYR carrying, MYR banked, MYR shortfall.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from books import App


def register(mcp: FastMCP, books: App) -> None:
    @mcp.resource("invoices://")
    def list_invoices() -> str:
        """Every invoice in the books, in issue order."""
        return json.dumps(
            [
                {
                    "id": i.id,
                    "number": i.number,
                    "party_id": i.party_id,
                    "party_name": i.party_name,
                    "currency": i.currency,
                    "amount_minor": i.amount_minor,
                    "carrying_minor": i.carrying_minor,
                    "banked_minor": i.banked_minor,
                    "status": i.status,
                }
                for i in books.invoicing.list_invoices()
            ]
        )

    @mcp.resource("invoices://{invoice_id}/settlement")
    def settlement(invoice_id: str) -> str:
        """The both-numbers settlement picture for one invoice. Path params
        arrive as strings, so coerce to int before lookup."""
        pic = books.invoicing.settlement_picture(int(invoice_id))
        return json.dumps(
            {
                "transaction_amount_minor": pic.transaction_amount.minor_units,
                "transaction_currency": pic.transaction_amount.currency.value,
                "carrying_minor": pic.carrying.minor_units,
                "banked_minor": pic.banked.minor_units,
                "shortfall_minor": pic.shortfall.minor_units,
            }
        )
