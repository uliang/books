"""General Ledger context — system of record (ADR-0008/0009/0013)."""

from books.general_ledger.period_lifecycle import PeriodClosedError

__all__ = ["PeriodClosedError"]
