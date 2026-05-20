"""Expense tools: the two buy-side rails (ADR-0003, amended).

- record_owner_paid_expense: owner used a personal card; the business
  owes the owner (Dr <category> / Cr Due to Owner).
- pay_contractor: business paid directly from the bank
  (Dr <category> / Cr Bank). Pure cash basis (ADR-0003).
- reimburse_owner is added in Task 9 (full rail closure).

The supplier Party is mandatory provenance for both — surfaced via
LookupError if party_id is unknown (the resolver in ExpenseManagement
calls PartyService.get which raises).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from books import App
from books.interfaces.mcp.forms import date_from, money_from_minor


def register(mcp: FastMCP, books: App) -> None:
    @mcp.tool()
    def record_owner_paid_expense(
        party_id: int,
        amount_minor: int,
        currency: str,
        category_account: str,
        on: str,
    ) -> dict:
        """Record a business expense the owner paid personally.

        Posts Dr <category_account> / Cr "Due to Owner" via the
        OwnerPaidExpenseRecorded event. The supplier Party
        (party_id) is mandatory provenance.

        `amount_minor` is signed minor units (e.g. cents for MYR);
        `on` is an ISO-8601 date (YYYY-MM-DD).
        """
        books.expense.record_owner_paid_expense(
            party_id=party_id,
            amount=money_from_minor(amount_minor, currency),
            category_account=category_account,
            on=date_from(on),
        )
        return {"recorded": True}

    @mcp.tool()
    def pay_contractor(
        party_id: int,
        amount_minor: int,
        currency: str,
        category_account: str,
        on: str,
    ) -> dict:
        """Record a direct-bank payment to a contractor.

        Posts Dr <category_account> / Cr "Bank" via the
        ContractorPaid event. Pure cash basis (ADR-0003): no
        payable, no accrual. The contractor's Party (party_id) is
        mandatory provenance.
        """
        books.expense.pay_contractor(
            party_id=party_id,
            amount=money_from_minor(amount_minor, currency),
            category_account=category_account,
            on=date_from(on),
        )
        return {"paid": True}
