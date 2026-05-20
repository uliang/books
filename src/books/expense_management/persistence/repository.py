"""Expense Management repository (ADR-0013 amended 2026-05-20)."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from books.expense_management.persistence.tables import (
    _ContractorPayment,
    _OwnerPaidExpense,
    _OwnerReimbursement,
)
from books.platform.repository import Repository


class ExpenseRepository(Repository):
    def add_owner_paid_expense(
        self,
        session: Session,
        *,
        party_id: int,
        party_name: str,
        amount_minor: int,
        category_account: str,
        on: date,
    ) -> None:
        session.add(
            _OwnerPaidExpense(
                party_id=party_id,
                party_name=party_name,
                amount_minor=amount_minor,
                category_account=category_account,
                on=on,
            )
        )

    def add_owner_reimbursement(
        self, session: Session, *, amount_minor: int, on: date
    ) -> None:
        session.add(_OwnerReimbursement(amount_minor=amount_minor, on=on))

    def add_contractor_payment(
        self,
        session: Session,
        *,
        party_id: int,
        party_name: str,
        amount_minor: int,
        category_account: str,
        on: date,
    ) -> None:
        session.add(
            _ContractorPayment(
                party_id=party_id,
                party_name=party_name,
                amount_minor=amount_minor,
                category_account=category_account,
                on=on,
            )
        )
