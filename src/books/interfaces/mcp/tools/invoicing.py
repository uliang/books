"""Invoicing tools: the sell-side lifecycle (ADR-0005, ADR-0019).

- issue_invoice: emits InvoiceIssued → GL Dr AR / Cr Revenue (MYR carrying).
- mark_paid: emits PaymentRecorded → GL Dr Bank / Cr AR; returns the
  resulting status so the agent knows whether adjudication follows.
- adjudicate_settlement: resolves a foreign-invoice MYR shortfall. The
  outcome is always supplied explicitly (ADR-0019); the system never
  decides FX vs underpayment.

The customer Party (party_id) is mandatory provenance on issue; an unknown
id surfaces as a LookupError (the injected resolver calls PartyService.get).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from books import App
from books.interfaces.mcp.forms import date_from, money_from_minor, rate_from_bp


def register(mcp: FastMCP, books: App) -> None:
    @mcp.tool()
    def issue_invoice(
        number: int,
        party_id: int,
        amount_minor: int,
        currency: str,
        issued_on: str,
        rate_bp: int = 10000,
    ) -> dict:
        """Issue an invoice to a customer.

        Posts Dr AR / Cr Revenue at the MYR carrying value via the
        InvoiceIssued event. `amount_minor`/`currency` are the transaction
        currency (e.g. SGD); `rate_bp` is the txn→MYR booking rate in
        integer basis points (×10000, e.g. 32000 = 3.20). MYR invoices
        ignore `rate_bp` (the domain forces rate 1). The customer
        `party_id` is mandatory provenance.
        """
        inv = books.invoicing.issue_invoice(
            number=number,
            party_id=party_id,
            amount=money_from_minor(amount_minor, currency),
            issued_on=date_from(issued_on),
            rate=rate_from_bp(rate_bp),
        )
        return {"invoice_id": inv.id, "number": inv.number}
