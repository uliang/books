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
from books.general_ledger import PeriodClosedError
from books.interfaces.mcp.forms import (
    date_from,
    money_from_minor,
    rate_from_bp,
    rejected_period,
)


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
        try:
            inv = books.invoicing.issue_invoice(
                number=number,
                party_id=party_id,
                amount=money_from_minor(amount_minor, currency),
                issued_on=date_from(issued_on),
                rate=rate_from_bp(rate_bp),
            )
        except PeriodClosedError as exc:
            return rejected_period(exc, "issue invoice")
        return {"invoice_id": inv.id, "number": inv.number}

    @mcp.tool()
    def mark_paid(
        invoice_id: int,
        paid_on: str,
        banked_minor: int | None = None,
        banked_currency: str = "MYR",
    ) -> dict:
        """Mark an invoice paid — the owner's assertion that funds were seen
        (CONTEXT / ADR-0004). Posts Dr Bank / Cr AR via PaymentRecorded.

        `banked_minor=None` means the full MYR carrying value landed (the
        domestic case). For a foreign invoice that banked fewer MYR, pass the
        actual MYR received; the shortfall stays open and the returned status
        is "awaiting_adjudication" (ADR-0005). Otherwise the status is "paid".
        """
        banked = (
            money_from_minor(banked_minor, banked_currency)
            if banked_minor is not None
            else None
        )
        try:
            books.invoicing.mark_paid(
                invoice_id=invoice_id,
                paid_on=date_from(paid_on),
                banked=banked,
            )
        except PeriodClosedError as exc:
            return rejected_period(exc, "record payment")
        picture = books.invoicing.settlement_picture(invoice_id)
        status = (
            "paid" if picture.shortfall.minor_units <= 0 else "awaiting_adjudication"
        )
        return {"status": status}

    @mcp.tool()
    def adjudicate_settlement(invoice_id: int, outcome: str, on: str) -> dict:
        """Resolve a foreign-invoice MYR shortfall (ADR-0005 / ADR-0019).

        `outcome` is supplied explicitly by the caller — the system never
        infers FX vs underpayment:
        - "settled_in_full": the gap is realized FX loss; emits
          SettlementAdjudicated → GL Dr FX Loss / Cr AR. Status → "paid".
        - "still_owes": a genuine underpayment; AR stays open, no FX posted.
          Status → "partially_paid".
        Any other outcome raises ValueError (surfaces as an error result).
        """
        try:
            books.invoicing.adjudicate_settlement(
                invoice_id=invoice_id,
                outcome=outcome,
                on=date_from(on),
            )
        except PeriodClosedError as exc:
            return rejected_period(exc, "adjudicate settlement")
        return {"status": "paid" if outcome == "settled_in_full" else "partially_paid"}
