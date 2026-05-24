# Cross-Context Transaction Atomicity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a use-case command and its synchronous event handlers run in one transaction, so a handler that rejects a write rolls back the whole command — no ghost records across contexts.

**Architecture:** Introduce a command-scoped `platform.UnitOfWork` that opens one SQLAlchemy `Session` and publishes it through a `contextvar`. Publisher commands (invoicing, expense) open the `UnitOfWork`; the GL event handlers pull that same session via `current_session()` instead of opening their own. The GL period gate raises a typed `PeriodClosedError`; MCP tools render it as a structured `rejected` result. The event bus is left untouched (stays a pure pub/sub).

**Tech Stack:** Python 3.13, SQLAlchemy (SQLite, `StaticPool`), `contextvars`, pytest, FastMCP, Flask. Run tests with `uv run pytest --timeout=60`, lint with `uv run ruff check src tests`, boundaries with `uv run lint-imports`.

**Reference:** spec at `docs/superpowers/specs/2026-05-24-cross-context-txn-atomicity-design.md`.

---

## Background the engineer must know

- **The bug:** `invoicing.issue_invoice` opens its repo's `unit_of_work()` (session A), flushes the invoice, then `bus.publish(InvoiceIssued)`; the GL handler `_on_invoice_issued` opens *its own* `unit_of_work()` (session B) and calls `append_entry`. When `append_entry` rejects a post into a closed period, session B rolls back but **session A's invoice is left committed** — a ghost invoice with no GL entry. Confirmed live 2026-05-24.
- **The fix:** one `Session` per command, shared by publisher and handler, committed once.
- **Roles auto-seed:** `LedgerService` seeds role→code defaults (`AR`, `Revenue`, `Bank`, `Write-off`, `Owner's Equity`, `Due to Owner`, `FX Loss`) but the **Chart accounts themselves must be created** in tests (`app.ledger.create_account(...)`).
- **In-memory app for tests:** `create_app("sqlite://")` gives a fresh app sharing one `StaticPool` connection. Service-level unit tests construct services directly with `Database()` + `EventBus()` (see `tests/test_invoicing.py`).
- **Keep `__str__` identical:** several tests do `pytest.raises(ValueError, match="2026-01")`. `PeriodClosedError` must subclass `ValueError` and keep the exact current message so those keep passing.

---

## Task 1: Platform `UnitOfWork` + contextvar

**Files:**
- Create: `src/books/platform/unit_of_work.py`
- Test: `tests/test_unit_of_work.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_unit_of_work.py
"""Command-scoped UnitOfWork (ADR-0011/0013): one session per command, shared
with synchronous handlers via a contextvar, committed exactly once."""

import pytest
from sqlalchemy import text

from books.platform.db import Database
from books.platform.unit_of_work import UnitOfWork, current_session


def test_commits_on_clean_exit_and_persists():
    db = Database()
    with UnitOfWork(db) as uow:
        uow.session.execute(text("CREATE TABLE t (n INTEGER)"))
        uow.session.execute(text("INSERT INTO t VALUES (1)"))

    with UnitOfWork(db) as uow:
        assert uow.session.execute(text("SELECT n FROM t")).scalar_one() == 1


def test_rolls_back_on_exception():
    db = Database()
    with UnitOfWork(db) as uow:
        uow.session.execute(text("CREATE TABLE t (n INTEGER)"))

    with pytest.raises(RuntimeError):  # noqa: SIM117
        with UnitOfWork(db) as uow:
            uow.session.execute(text("INSERT INTO t VALUES (99)"))
            raise RuntimeError("boom")

    with UnitOfWork(db) as uow:
        assert uow.session.execute(text("SELECT count(*) FROM t")).scalar_one() == 0


def test_current_session_is_the_active_uow_session():
    db = Database()
    with UnitOfWork(db) as uow:
        assert current_session() is uow.session


def test_current_session_outside_a_uow_raises():
    with pytest.raises(RuntimeError, match="no active UnitOfWork"):
        current_session()


def test_contextvar_resets_between_sequential_commands():
    db = Database()
    with UnitOfWork(db):
        pass
    with pytest.raises(RuntimeError, match="no active UnitOfWork"):
        current_session()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_unit_of_work.py -v`
Expected: FAIL with `ModuleNotFoundError: books.platform.unit_of_work`.

- [ ] **Step 3: Write the implementation**

```python
# src/books/platform/unit_of_work.py
"""Command-scoped unit of work (ADR-0011/0013, amended 2026-05-24).

One use-case command = one transaction. ``UnitOfWork`` opens a single
SQLAlchemy ``Session`` and publishes it through a ``contextvar`` so the
publisher's synchronous event handlers post into the *same* session and the
whole command commits or rolls back as one. This restores ADR-0011's
"dispatch inside the same transaction" guarantee that the 2026-05-20
per-context-repository UoW change silently regressed.

This is plumbing (session/transaction lifecycle) — no domain concepts — so it
belongs in ``platform/``.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from sqlalchemy.orm import Session

from books.platform.db import Database

_active_session: ContextVar[Session | None] = ContextVar(
    "active_session", default=None
)


def current_session() -> Session:
    """The session of the active command's UnitOfWork. Raises if called
    outside one — handlers must run inside the publisher's transaction."""
    session = _active_session.get()
    if session is None:
        raise RuntimeError("no active UnitOfWork")
    return session


class UnitOfWork:
    """The command-scoped transaction: ONE session, committed exactly once,
    visible to synchronous handlers via ``current_session()``."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self.session: Session | None = None
        self._token: Token[Session | None] | None = None

    def __enter__(self) -> UnitOfWork:
        self.session = Session(self._db.engine)
        self._token = _active_session.set(self.session)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            _active_session.reset(self._token)
            self.session.close()
            self.session = None
            self._token = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_unit_of_work.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/books/platform/unit_of_work.py tests/test_unit_of_work.py
git commit -m "feat(platform): command-scoped UnitOfWork + current_session contextvar"
```

---

## Task 2: `PeriodClosedError` + public re-export

**Files:**
- Modify: `src/books/general_ledger/period_lifecycle.py`
- Modify: `src/books/general_ledger/__init__.py` (currently empty)
- Test: `tests/test_period_lifecycle.py` (append)

- [ ] **Step 1: Write the failing test (append to the file)**

```python
# tests/test_period_lifecycle.py  (add these imports + tests)
from datetime import date

from books.general_ledger import PeriodClosedError as ReexportedPeriodClosedError
from books.general_ledger.period_lifecycle import PeriodClosedError, PeriodState


def test_period_closed_error_is_a_value_error_carrying_fields():
    err = PeriodClosedError(
        period="2026-01",
        state=PeriodState.SOFT,
        source_kind="InvoiceIssued",
        on=date(2026, 1, 15),
    )
    assert isinstance(err, ValueError)
    assert err.period == "2026-01"
    assert err.state is PeriodState.SOFT
    assert err.source_kind == "InvoiceIssued"
    assert err.on == date(2026, 1, 15)
    # __str__ matches the legacy append_entry message verbatim (match-based
    # tests rely on it).
    assert str(err) == (
        "period 2026-01 is soft-closed: cannot post InvoiceIssued on 2026-01-15"
    )


def test_period_closed_error_is_re_exported_from_the_context():
    assert ReexportedPeriodClosedError is PeriodClosedError
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_period_lifecycle.py -k period_closed_error -v`
Expected: FAIL with `ImportError: cannot import name 'PeriodClosedError'`.

- [ ] **Step 3: Add the exception to `period_lifecycle.py`**

Add after the `PeriodState` enum (keep `from datetime import date` import at top — add it):

```python
# src/books/general_ledger/period_lifecycle.py  (add `from datetime import date`
# to the imports, then add this class after PeriodState)

class PeriodClosedError(ValueError):
    """A post was rejected because its target period does not admit this
    source_kind (ADR-0009). Subclasses ``ValueError`` so existing ``except
    ValueError`` sites and ``pytest.raises(ValueError, match=...)`` keep
    working; carries structured fields for interfaces to render."""

    def __init__(
        self, *, period: str, state: PeriodState, source_kind: str, on: date
    ) -> None:
        self.period = period
        self.state = state
        self.source_kind = source_kind
        self.on = on
        super().__init__(
            f"period {period} is {state.value}-closed: "
            f"cannot post {source_kind} on {on}"
        )
```

- [ ] **Step 4: Re-export from the context surface**

```python
# src/books/general_ledger/__init__.py  (replace the file contents)
"""General Ledger context — system of record (ADR-0008/0009/0013)."""

from books.general_ledger.period_lifecycle import PeriodClosedError

__all__ = ["PeriodClosedError"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_period_lifecycle.py -k period_closed_error -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/books/general_ledger/period_lifecycle.py src/books/general_ledger/__init__.py tests/test_period_lifecycle.py
git commit -m "feat(general_ledger): typed PeriodClosedError + public re-export"
```

---

## Task 3: `append_entry` raises `PeriodClosedError`

**Files:**
- Modify: `src/books/general_ledger/persistence/repository.py` (the `append_entry` gate, ~line 117-122)
- Test: `tests/test_period_state_gating.py` (append one assertion)

- [ ] **Step 1: Write the failing test (append to the file)**

```python
# tests/test_period_state_gating.py  (add imports + test)
import pytest

from books.general_ledger import PeriodClosedError
from books.general_ledger.period_lifecycle import PeriodState


def test_append_into_soft_month_raises_typed_period_closed_error():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    app.ledger.soft_close("2026-01")

    with pytest.raises(PeriodClosedError) as exc:
        app.invoicing.issue_invoice(
            number=1,
            party_id=acme.id,
            amount=Money.myr(500_00),
            issued_on=date(2026, 1, 15),
        )
    assert exc.value.period == "2026-01"
    assert exc.value.state is PeriodState.SOFT
    assert exc.value.source_kind == "InvoiceIssued"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_period_state_gating.py -k typed_period_closed -v`
Expected: FAIL — a bare `ValueError` is raised, not `PeriodClosedError`.

- [ ] **Step 3: Change the raise in `append_entry`**

In `src/books/general_ledger/persistence/repository.py`, update the import and the gate:

```python
# import line ~21 — add PeriodClosedError
from books.general_ledger.period_lifecycle import PeriodClosedError, PeriodState, may_post
```

```python
# in append_entry, replace the existing raise:
        period = period_of(on)
        state = self.period_state(session, period)
        if not may_post(state, source_kind):
            raise PeriodClosedError(
                period=period, state=state, source_kind=source_kind, on=on
            )
```

- [ ] **Step 4: Run the gating + lifecycle tests**

Run: `uv run pytest tests/test_period_state_gating.py tests/test_period_transitions.py tests/test_period_lifecycle.py tests/test_increment_2_soft_close_carry_forward.py -v`
Expected: PASS — the new typed test passes and all existing `match="2026-01"` assertions still pass (identical `__str__`).

- [ ] **Step 5: Commit**

```bash
git add src/books/general_ledger/persistence/repository.py tests/test_period_state_gating.py
git commit -m "feat(general_ledger): append_entry raises typed PeriodClosedError"
```

---

## Task 4: First flow — `issue_invoice` ⇒ `_on_invoice_issued` in one transaction (the tracer)

This task wires the `UnitOfWork` factory into `InvoicingService`, converts the
`issue_invoice` command and the `_on_invoice_issued` handler, and proves the
ghost-invoice bug is fixed end-to-end.

**Files:**
- Modify: `src/books/invoicing/service.py` (`__init__`, `issue_invoice`)
- Modify: `src/books/general_ledger/service.py` (`_on_invoice_issued`, add import)
- Modify: `src/books/__init__.py` (inject `unit_of_work` into `InvoicingService`)
- Test: `tests/test_cross_context_atomicity.py` (new)

- [ ] **Step 1: Write the failing acceptance test**

```python
# tests/test_cross_context_atomicity.py
"""A command and its synchronous handler share one transaction: a handler
rejection rolls back the whole command, leaving NO ghost rows in any context
(the bug found in the PR #4 live trial, 2026-05-24)."""

from __future__ import annotations

from datetime import date

import pytest

from books import create_app
from books.general_ledger import PeriodClosedError
from books.platform.money import Money


def _chart(app):
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(code="Write-off", name="Write-off", type="expense")
    app.ledger.create_account(
        code="Owner's Equity", name="Owner's Equity", type="equity"
    )


def test_issue_into_closed_period_rolls_back_both_contexts():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    app.ledger.soft_close("2026-01")

    with pytest.raises(PeriodClosedError):
        app.invoicing.issue_invoice(
            number=1,
            party_id=acme.id,
            amount=Money.myr(1000_00),
            issued_on=date(2026, 1, 15),
        )

    # invoicing context: no ghost invoice
    assert app.invoicing.list_invoices() == []
    # general-ledger context: no postings leaked
    assert app.ledger.postings_for(code="AR") == []
    assert app.ledger.postings_for(code="Revenue") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cross_context_atomicity.py -v`
Expected: FAIL — `PeriodClosedError` is raised, but `list_invoices()` returns the ghost invoice (assertion fails). If it unexpectedly passes, STOP: the in-memory case isn't reproducing the ghost — investigate before continuing.

- [ ] **Step 3: Wire the UnitOfWork factory into `InvoicingService.__init__`**

```python
# src/books/invoicing/service.py
# add imports near the top:
from collections.abc import Callable   # (if not already imported)
from books.platform.unit_of_work import UnitOfWork

# replace __init__:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        party_name: Callable[[int], str],
        unit_of_work: Callable[[], UnitOfWork] | None = None,
    ) -> None:
        self._repo = InvoiceRepository(db)
        self._bus = bus
        self._party_name = party_name
        self._uow = unit_of_work or (lambda: UnitOfWork(db))
```

- [ ] **Step 4: Convert the `issue_invoice` command**

```python
# src/books/invoicing/service.py — issue_invoice body (replace the `with` block)
        carrying_minor = _to_myr(amount.minor_units, rate)
        with self._uow() as uow:
            row = self._repo.add(
                uow.session,
                number=number,
                party_id=party_id,
                amount_minor=amount.minor_units,
                currency=amount.currency.value,
                rate=str(rate),
                carrying_minor=carrying_minor,
                issued_on=issued_on,
            )
            # The Ledger is MYR system-of-record: it sees the carrying value.
            self._bus.publish(
                InvoiceIssued(
                    invoice_number=number,
                    party_id=party_id,
                    party_name=self._party_name(party_id),
                    amount=Money.myr(carrying_minor),
                    issued_on=issued_on,
                )
            )
            return Invoice(id=row.id, number=row.number)
```

- [ ] **Step 5: Convert the `_on_invoice_issued` handler**

```python
# src/books/general_ledger/service.py
# add import near the top:
from books.platform.unit_of_work import current_session

# replace _on_invoice_issued:
    def _on_invoice_issued(self, e: InvoiceIssued) -> None:
        amt = e.amount.minor_units
        session = current_session()
        ar = self._repo.role_code(session, "ar")
        revenue = self._repo.role_code(session, "revenue")
        self._repo.append_entry(
            session,
            on=e.issued_on,
            narrative=f"Invoice #{e.invoice_number} to {e.party_name}",
            source_kind="InvoiceIssued",
            source_id=str(e.invoice_number),
            legs=[
                (ar, amt, _party_dim(e.party_id, e.party_name)),
                (revenue, -amt, None),
            ],
        )
```

- [ ] **Step 6: Inject the factory at the composition root**

```python
# src/books/__init__.py
# add import:
from books.platform.unit_of_work import UnitOfWork

# update the invoicing wiring:
    invoicing = InvoicingService(
        db,
        bus,
        party_name=lambda pid: party.get(pid).name,
        unit_of_work=lambda: UnitOfWork(db),
    )
```

- [ ] **Step 7: Run the acceptance test + invoicing/ledger suites**

Run: `uv run pytest tests/test_cross_context_atomicity.py tests/test_invoicing.py tests/test_general_ledger.py tests/test_tracer_thread_1.py -v`
Expected: PASS — no ghost invoice, no GL postings; existing invoicing/ledger tracer tests still green.

- [ ] **Step 8: Commit**

```bash
git add src/books/invoicing/service.py src/books/general_ledger/service.py src/books/__init__.py tests/test_cross_context_atomicity.py
git commit -m "feat: issue_invoice + GL handler share one transaction (atomic rollback)"
```

---

## Task 5: `mark_paid` ⇒ `_on_payment_recorded` in one transaction

**Files:**
- Modify: `src/books/invoicing/service.py` (`mark_paid`)
- Modify: `src/books/general_ledger/service.py` (`_on_payment_recorded`)
- Test: `tests/test_cross_context_atomicity.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cross_context_atomicity.py  (append)
def test_mark_paid_into_closed_period_rolls_back_both_contexts():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 2, 10),   # February: open
    )
    app.ledger.soft_close("2026-03")

    with pytest.raises(PeriodClosedError):
        app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 3, 5))

    # No Bank posting leaked, and the invoice status stayed "issued".
    assert app.ledger.postings_for(code="Bank") == []
    (row,) = [i for i in app.invoicing.list_invoices() if i.id == inv.id]
    assert row.status == "issued"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cross_context_atomicity.py -k mark_paid_into_closed -v`
Expected: FAIL — a Bank posting and/or a status change leaks (separate transactions).

- [ ] **Step 3: Convert `mark_paid`**

```python
# src/books/invoicing/service.py — mark_paid body (replace `with` block)
        with self._uow() as uow:
            invoice = self._repo.get(uow.session, invoice_id)
            if invoice is None:
                raise LookupError(f"no invoice {invoice_id}")
            banked_minor = (
                invoice.carrying_minor if banked is None else banked.minor_units
            )
            status = (
                "paid"
                if banked_minor >= invoice.carrying_minor
                else "awaiting_adjudication"
            )
            self._repo.record_payment(
                uow.session, invoice_id, banked_minor=banked_minor, status=status
            )
            self._bus.publish(
                PaymentRecorded(
                    invoice_number=invoice.number,
                    party_id=invoice.party_id,
                    amount=Money.myr(banked_minor),
                    paid_on=paid_on,
                )
            )
```

- [ ] **Step 4: Convert `_on_payment_recorded`**

```python
# src/books/general_ledger/service.py — replace _on_payment_recorded
    def _on_payment_recorded(self, e: PaymentRecorded) -> None:
        amt = e.amount.minor_units
        session = current_session()
        ar = self._repo.role_code(session, "ar")
        bank = self._repo.role_code(session, "bank")
        party_name = self._repo.ar_party_name(session, ar, e.party_id)
        self._repo.append_entry(
            session,
            on=e.paid_on,
            narrative=f"Payment for invoice #{e.invoice_number}",
            source_kind="PaymentRecorded",
            source_id=str(e.invoice_number),
            legs=[
                (bank, amt, None),
                (ar, -amt, _party_dim(e.party_id, party_name)),
            ],
        )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_cross_context_atomicity.py tests/test_invoicing.py tests/test_increment_3_fx_adjudication.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/books/invoicing/service.py src/books/general_ledger/service.py tests/test_cross_context_atomicity.py
git commit -m "feat: mark_paid + GL payment handler share one transaction"
```

---

## Task 6: `adjudicate_settlement` ⇒ `_on_settlement_adjudicated` in one transaction

**Files:**
- Modify: `src/books/invoicing/service.py` (`adjudicate_settlement`)
- Modify: `src/books/general_ledger/service.py` (`_on_settlement_adjudicated`)
- Test: `tests/test_cross_context_atomicity.py` (append)

- [ ] **Step 1: Write the failing test**

First add two imports to the top of `tests/test_cross_context_atomicity.py`:

```python
from decimal import Decimal

from books.platform.money import Currency, Money   # Money already imported — widen this line
```

Then append the test:

```python
# tests/test_cross_context_atomicity.py  (append)
def test_adjudicate_into_closed_period_rolls_back_both_contexts():
    app = create_app("sqlite://")
    _chart(app)
    app.ledger.create_account(code="FX Loss", name="FX Loss", type="expense")
    acme = app.party.register_party(name="Acme", role="customer")
    # Foreign invoice that banks short, so a shortfall is open to adjudicate.
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money(1000_00, Currency("SGD")),
        issued_on=date(2026, 2, 1),
        rate=Decimal("3.0"),
    )
    app.invoicing.mark_paid(
        invoice_id=inv.id, paid_on=date(2026, 2, 20), banked=Money.myr(2900_00)
    )
    app.ledger.soft_close("2026-04")

    with pytest.raises(PeriodClosedError):
        app.invoicing.adjudicate_settlement(
            invoice_id=inv.id, outcome="settled_in_full", on=date(2026, 4, 3)
        )

    # No FX Loss posting leaked, and the invoice status did not flip to "paid".
    assert app.ledger.postings_for(code="FX Loss") == []
    (row,) = [i for i in app.invoicing.list_invoices() if i.id == inv.id]
    assert row.status == "awaiting_adjudication"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cross_context_atomicity.py -k adjudicate_into_closed -v`
Expected: FAIL — status flips to "paid" even though the FX posting is rejected (separate transactions).

- [ ] **Step 3: Convert `adjudicate_settlement`**

```python
# src/books/invoicing/service.py — adjudicate_settlement body (replace `with` block)
        with self._uow() as uow:
            invoice = self._repo.get(uow.session, invoice_id)
            if invoice is None:
                raise LookupError(f"no invoice {invoice_id}")
            shortfall = invoice.carrying_minor - (invoice.banked_minor or 0)
            if outcome == "settled_in_full":
                self._repo.set_status(uow.session, invoice_id, "paid")
                self._bus.publish(
                    SettlementAdjudicated(
                        invoice_number=invoice.number,
                        party_id=invoice.party_id,
                        fx_loss=Money.myr(shortfall),
                        on=on,
                    )
                )
            elif outcome == "still_owes":
                self._repo.set_status(uow.session, invoice_id, "partially_paid")
            else:
                raise ValueError(f"unknown adjudication outcome: {outcome!r}")
```

- [ ] **Step 4: Convert `_on_settlement_adjudicated`**

```python
# src/books/general_ledger/service.py — replace _on_settlement_adjudicated
    def _on_settlement_adjudicated(self, e: SettlementAdjudicated) -> None:
        loss = e.fx_loss.minor_units
        if loss == 0:
            return
        session = current_session()
        ar = self._repo.role_code(session, "ar")
        fx_loss = self._repo.role_code(session, "fx_loss")
        party_name = self._repo.ar_party_name(session, ar, e.party_id)
        self._repo.append_entry(
            session,
            on=e.on,
            narrative=(
                f"Realized FX loss on settlement of invoice #{e.invoice_number}"
            ),
            source_kind="GuidedJournal",
            source_id=str(e.invoice_number),
            legs=[
                (fx_loss, loss, None),
                (ar, -loss, _party_dim(e.party_id, party_name)),
            ],
        )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_cross_context_atomicity.py tests/test_increment_3_fx_adjudication.py tests/test_mcp_invoice_fx.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/books/invoicing/service.py src/books/general_ledger/service.py tests/test_cross_context_atomicity.py
git commit -m "feat: adjudicate_settlement + GL FX handler share one transaction"
```

---

## Task 7: Expense rail — wire UoW + convert `record_owner_paid_expense` ⇒ `_on_owner_paid_expense`

**Files:**
- Modify: `src/books/expense_management/service.py` (`__init__`, `record_owner_paid_expense`)
- Modify: `src/books/general_ledger/service.py` (`_on_owner_paid_expense`)
- Modify: `src/books/__init__.py` (inject `unit_of_work` into `ExpenseManagementService`)
- Test: `tests/test_cross_context_atomicity.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cross_context_atomicity.py  (append)
def test_owner_paid_expense_into_closed_period_rolls_back_both_contexts():
    app = create_app("sqlite://")
    _chart(app)
    app.ledger.create_account(code="Due to Owner", name="Due to Owner", type="liability")
    app.ledger.create_account(code="Office", name="Office", type="expense")
    supplier = app.party.register_party(name="Stationers", role="supplier")
    app.ledger.soft_close("2026-01")

    with pytest.raises(PeriodClosedError):
        app.expense.record_owner_paid_expense(
            party_id=supplier.id,
            amount=Money.myr(120_00),
            category_account="Office",
            on=date(2026, 1, 9),
        )

    assert app.ledger.postings_for(code="Office") == []
    assert app.ledger.postings_for(code="Due to Owner") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cross_context_atomicity.py -k owner_paid_expense_into_closed -v`
Expected: FAIL — the expense record persists though the GL post is rejected.

- [ ] **Step 3: Wire the factory into `ExpenseManagementService.__init__`**

```python
# src/books/expense_management/service.py
# add imports:
from books.platform.unit_of_work import UnitOfWork

# replace __init__:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        party_name: Callable[[int], str],
        unit_of_work: Callable[[], UnitOfWork] | None = None,
    ) -> None:
        self._repo = ExpenseRepository(db)
        self._bus = bus
        self._party_name = party_name
        self._uow = unit_of_work or (lambda: UnitOfWork(db))
```

- [ ] **Step 4: Convert `record_owner_paid_expense`**

```python
# src/books/expense_management/service.py — replace the `with` block
        name = self._party_name(party_id)
        with self._uow() as uow:
            self._repo.add_owner_paid_expense(
                uow.session,
                party_id=party_id,
                party_name=name,
                amount_minor=amount.minor_units,
                category_account=category_account,
                on=on,
            )
            self._bus.publish(
                OwnerPaidExpenseRecorded(
                    party_id=party_id,
                    party_name=name,
                    amount=amount,
                    category_account=category_account,
                    on=on,
                )
            )
```

- [ ] **Step 5: Convert `_on_owner_paid_expense`**

```python
# src/books/general_ledger/service.py — replace _on_owner_paid_expense
    def _on_owner_paid_expense(self, e: OwnerPaidExpenseRecorded) -> None:
        amt = e.amount.minor_units
        session = current_session()
        due = self._repo.role_code(session, "due_to_owner")
        self._repo.append_entry(
            session,
            on=e.on,
            narrative=f"Owner-paid expense: {e.party_name}",
            source_kind="OwnerPaidExpenseRecorded",
            source_id=str(e.party_id),
            legs=[
                (e.category_account, amt, _party_dim(e.party_id, e.party_name)),
                (due, -amt, None),
            ],
        )
```

- [ ] **Step 6: Inject the factory at the composition root**

```python
# src/books/__init__.py — update the expense wiring
    expense = ExpenseManagementService(
        db,
        bus,
        party_name=lambda pid: party.get(pid).name,
        unit_of_work=lambda: UnitOfWork(db),
    )
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_cross_context_atomicity.py tests/test_owner_reimbursable_expense.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/books/expense_management/service.py src/books/general_ledger/service.py src/books/__init__.py tests/test_cross_context_atomicity.py
git commit -m "feat: owner-paid-expense + GL handler share one transaction"
```

---

## Task 8: `pay_contractor` ⇒ `_on_contractor_paid` in one transaction

**Files:**
- Modify: `src/books/expense_management/service.py` (`pay_contractor`)
- Modify: `src/books/general_ledger/service.py` (`_on_contractor_paid`)
- Test: `tests/test_cross_context_atomicity.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cross_context_atomicity.py  (append)
def test_pay_contractor_into_closed_period_rolls_back_both_contexts():
    app = create_app("sqlite://")
    _chart(app)
    app.ledger.create_account(code="Subcontract", name="Subcontract", type="expense")
    bob = app.party.register_party(name="Bob", role="supplier")
    app.ledger.soft_close("2026-01")

    with pytest.raises(PeriodClosedError):
        app.expense.pay_contractor(
            party_id=bob.id,
            amount=Money.myr(300_00),
            category_account="Subcontract",
            on=date(2026, 1, 20),
        )

    assert app.ledger.postings_for(code="Subcontract") == []
    assert app.ledger.postings_for(code="Bank") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cross_context_atomicity.py -k pay_contractor_into_closed -v`
Expected: FAIL — the contractor payment record persists.

- [ ] **Step 3: Convert `pay_contractor`**

```python
# src/books/expense_management/service.py — replace the `with` block
        name = self._party_name(party_id)
        with self._uow() as uow:
            self._repo.add_contractor_payment(
                uow.session,
                party_id=party_id,
                party_name=name,
                amount_minor=amount.minor_units,
                category_account=category_account,
                on=on,
            )
            self._bus.publish(
                ContractorPaid(
                    party_id=party_id,
                    party_name=name,
                    amount=amount,
                    category_account=category_account,
                    on=on,
                )
            )
```

- [ ] **Step 4: Convert `_on_contractor_paid`**

```python
# src/books/general_ledger/service.py — replace _on_contractor_paid
    def _on_contractor_paid(self, e: ContractorPaid) -> None:
        amt = e.amount.minor_units
        session = current_session()
        bank = self._repo.role_code(session, "bank")
        self._repo.append_entry(
            session,
            on=e.on,
            narrative=f"Contractor payment: {e.party_name}",
            source_kind="ContractorPaid",
            source_id=str(e.party_id),
            legs=[
                (e.category_account, amt, _party_dim(e.party_id, e.party_name)),
                (bank, -amt, None),
            ],
        )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_cross_context_atomicity.py tests/test_contractor_payment.py tests/test_mcp_contractor.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/books/expense_management/service.py src/books/general_ledger/service.py tests/test_cross_context_atomicity.py
git commit -m "feat: pay_contractor + GL handler share one transaction"
```

---

## Task 9: `reimburse_owner` ⇒ `_on_owner_reimbursed` in one transaction

**Files:**
- Modify: `src/books/expense_management/service.py` (`reimburse_owner`)
- Modify: `src/books/general_ledger/service.py` (`_on_owner_reimbursed`)
- Test: `tests/test_cross_context_atomicity.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cross_context_atomicity.py  (append)
def test_reimburse_owner_into_closed_period_rolls_back_both_contexts():
    app = create_app("sqlite://")
    _chart(app)
    app.ledger.create_account(code="Due to Owner", name="Due to Owner", type="liability")
    app.ledger.soft_close("2026-01")

    with pytest.raises(PeriodClosedError):
        app.expense.reimburse_owner(amount=Money.myr(200_00), on=date(2026, 1, 12))

    assert app.ledger.postings_for(code="Due to Owner") == []
    assert app.ledger.postings_for(code="Bank") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cross_context_atomicity.py -k reimburse_owner_into_closed -v`
Expected: FAIL — the reimbursement record persists.

- [ ] **Step 3: Convert `reimburse_owner`**

```python
# src/books/expense_management/service.py — replace the `with` block
        with self._uow() as uow:
            self._repo.add_owner_reimbursement(
                uow.session, amount_minor=amount.minor_units, on=on
            )
            self._bus.publish(OwnerReimbursed(amount=amount, on=on))
```

- [ ] **Step 4: Convert `_on_owner_reimbursed`**

```python
# src/books/general_ledger/service.py — replace _on_owner_reimbursed
    def _on_owner_reimbursed(self, e: OwnerReimbursed) -> None:
        amt = e.amount.minor_units
        session = current_session()
        due = self._repo.role_code(session, "due_to_owner")
        bank = self._repo.role_code(session, "bank")
        self._repo.append_entry(
            session,
            on=e.on,
            narrative="Reimbursement to owner",
            source_kind="OwnerReimbursed",
            source_id=e.on.isoformat(),
            legs=[
                (due, amt, None),
                (bank, -amt, None),
            ],
        )
```

- [ ] **Step 5: Run the FULL suite (all handlers now converted)**

Run: `uv run pytest --timeout=60`
Expected: PASS — every flow now shares one transaction; no test relies on the old per-context UoW for a publisher command.

- [ ] **Step 6: Commit**

```bash
git add src/books/expense_management/service.py src/books/general_ledger/service.py tests/test_cross_context_atomicity.py
git commit -m "feat: reimburse_owner + GL handler share one transaction"
```

---

## Task 10: MCP — structured `rejected` result for closed-period posts

**Files:**
- Modify: `src/books/interfaces/mcp/forms.py` (add `rejected_period`)
- Modify: `src/books/interfaces/mcp/tools/invoicing.py` (wrap 3 tools)
- Modify: `src/books/interfaces/mcp/tools/expense.py` (wrap 3 tools)
- Test: `tests/test_mcp_period_close.py` (append) — uses helpers in `tests/_mcp_helpers.py`

- [ ] **Step 1: Write the failing test**

This file already uses `from _mcp_helpers import mcp_client, run`, builds an
in-memory `app`, and parses tool results as
`json.loads(result.content[0].text)`. Mirror that exactly:

```python
# tests/test_mcp_period_close.py  (append)
def test_issue_invoice_into_closed_period_returns_structured_rejected():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.party.register_party(name="Acme", role="customer")  # id 1
    app.ledger.soft_close("2026-01")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "issue_invoice",
                {
                    "number": 1,
                    "party_id": 1,
                    "amount_minor": 1000_00,
                    "currency": "MYR",
                    "issued_on": "2026-01-15",
                },
            )
            payload = json.loads(result.content[0].text)
            assert payload["status"] == "rejected"
            assert payload["reason"] == "period_closed"
            assert payload["period"] == "2026-01"
            assert payload["state"] == "soft"
            assert "2026-01" in payload["message"]

    run(scenario())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_period_close.py -k structured_rejected -v`
Expected: FAIL — the tool currently raises (FastMCP error result), no `rejected` dict.

- [ ] **Step 3: Add the shared formatter**

```python
# src/books/interfaces/mcp/forms.py  (append)
from books.general_ledger import PeriodClosedError


def rejected_period(exc: PeriodClosedError, action: str) -> dict:
    """Render a PeriodClosedError as a structured rejection (mirrors
    hard_close's "blocked" result) so the agent gets actionable fields, not a
    stack-trace string. `action` is a short verb phrase, e.g. "issue invoice"."""
    return {
        "status": "rejected",
        "reason": "period_closed",
        "period": exc.period,
        "state": exc.state.value,
        "message": (
            f"cannot {action} dated {exc.on.isoformat()}: "
            f"period {exc.period} is {exc.state.value}-closed"
        ),
    }
```

- [ ] **Step 4: Wrap the invoicing tools**

```python
# src/books/interfaces/mcp/tools/invoicing.py
# add import:
from books.general_ledger import PeriodClosedError
from books.interfaces.mcp.forms import rejected_period

# issue_invoice body — wrap the domain call:
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

# mark_paid body — wrap the mark_paid call:
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

# adjudicate_settlement body — wrap the call:
        try:
            books.invoicing.adjudicate_settlement(
                invoice_id=invoice_id,
                outcome=outcome,
                on=date_from(on),
            )
        except PeriodClosedError as exc:
            return rejected_period(exc, "adjudicate settlement")
        return {"status": "paid" if outcome == "settled_in_full" else "partially_paid"}
```

- [ ] **Step 5: Wrap the expense tools**

```python
# src/books/interfaces/mcp/tools/expense.py
# add import:
from books.general_ledger import PeriodClosedError
from books.interfaces.mcp.forms import rejected_period

# record_owner_paid_expense body:
        try:
            books.expense.record_owner_paid_expense(
                party_id=party_id,
                amount=money_from_minor(amount_minor, currency),
                category_account=category_account,
                on=date_from(on),
            )
        except PeriodClosedError as exc:
            return rejected_period(exc, "record owner-paid expense")
        return {"recorded": True}

# pay_contractor body:
        try:
            books.expense.pay_contractor(
                party_id=party_id,
                amount=money_from_minor(amount_minor, currency),
                category_account=category_account,
                on=date_from(on),
            )
        except PeriodClosedError as exc:
            return rejected_period(exc, "pay contractor")
        return {"paid": True}

# reimburse_owner body:
        try:
            books.expense.reimburse_owner(
                amount=money_from_minor(amount_minor, currency),
                on=date_from(on),
            )
        except PeriodClosedError as exc:
            return rejected_period(exc, "reimburse owner")
        return {"reimbursed": True}
```

- [ ] **Step 6: Run MCP tests**

Run: `uv run pytest tests/test_mcp_period_close.py tests/test_mcp_invoicing_tools.py tests/test_mcp_expense_tools.py tests/test_mcp_errors.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/books/interfaces/mcp/forms.py src/books/interfaces/mcp/tools/invoicing.py src/books/interfaces/mcp/tools/expense.py tests/test_mcp_period_close.py
git commit -m "feat(mcp): structured 'rejected' result for closed-period posts"
```

---

## Task 11: Web — confirm the clean flash (no code change)

The web layer already has a global `@errorhandler(ValueError)` that flashes
`str(exc)`. `PeriodClosedError` is a `ValueError` with a clean `__str__`, so
this works without code changes; this task locks it in with a test.

**Files:**
- Test: `tests/test_web_invoicing.py` (append) — uses the file's `_app_client()` and `_setup()` helpers (mirrors `test_unknown_invoice_mark_paid_flashes_not_500`).

- [ ] **Step 1: Write the test**

```python
# tests/test_web_invoicing.py  (append)
def test_issue_into_closed_period_flashes_clean_message():
    books, c = _app_client()
    acme = _setup(books)
    books.ledger.soft_close("2026-01")
    resp = c.post(
        "/invoicing/issue",
        data={
            "number": "1",
            "party_id": str(acme.id),
            "amount": "1000.00",
            "currency": "MYR",
            "issued_on": "2026-01-15",
            "rate": "1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-01" in body
    assert "closed" in body
    # no ghost invoice persisted
    assert books.invoicing.list_invoices() == []
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_web_invoicing.py -k closed_period_flashes -v`
Expected: PASS (the existing `@errorhandler(ValueError)` flashes `str(exc)`; the atomic fix from Task 4 prevents the ghost).

- [ ] **Step 3: Commit**

```bash
git add tests/test_web_invoicing.py
git commit -m "test(web): closed-period issue flashes clean message, no ghost invoice"
```

---

## Task 12: ADR amendments + spec status

**Files:**
- Modify: `docs/adr/0013-persistence-module-layout-and-enforced-boundaries.md`
- Modify: `docs/adr/0011-modular-monolith-synchronous-event-integration.md`
- Modify: `docs/superpowers/specs/2026-05-24-cross-context-txn-atomicity-design.md` (status line)

- [ ] **Step 1: Amend ADR-0013** — append a dated amendment:

```markdown
## Amendment 2026-05-24 — the command owns the unit of work

The 2026-05-20 amendment placed the unit of work on each per-context
repository. That silently split a use-case command from its synchronous event
handler into *two* transactions (publisher in one `Session`, handler in
another), so a handler rejection left the publisher's write committed — a torn
cross-context write (a ghost invoice on a post into a closed period).

Transaction ownership moves up to a command-scoped `platform.UnitOfWork`: one
`Session` per command, published to handlers via a `contextvar`
(`current_session()`). Publisher commands (invoicing, expense) open the
`UnitOfWork`; the Ledger's event handlers pull that session instead of opening
their own. Repository methods keep their `session`-first signatures unchanged.
`Repository.unit_of_work()` is retained for read-only/query paths and the
Ledger's self-contained command writes; the rule is: *if a command publishes
(or its handler writes), it uses the platform `UnitOfWork`.* This restores
ADR-0011's "one transaction per use-case command."
```

- [ ] **Step 2: Amend ADR-0011** — append a short note:

```markdown
## Note 2026-05-24 — how "same transaction" is realized

"Dispatch runs inside the same transaction as the publisher" is realized by the
command-scoped `platform.UnitOfWork` (ADR-0013, amended): handlers run in the
publisher's `UnitOfWork` and read its session via `current_session()`. The bus
contract is unchanged — it stays a pure synchronous pub/sub of single-arg
handlers.
```

- [ ] **Step 3: Update the spec status line**

Change the spec header `**Status:**` to `Implemented`.

- [ ] **Step 4: Final full verification**

Run: `uv run pytest --timeout=60 && uv run ruff check src tests && uv run lint-imports`
Expected: all tests pass, ruff clean, 6/6 import contracts pass.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0011-modular-monolith-synchronous-event-integration.md docs/adr/0013-persistence-module-layout-and-enforced-boundaries.md docs/superpowers/specs/2026-05-24-cross-context-txn-atomicity-design.md
git commit -m "docs: amend ADR-0011/0013 for command-scoped UnitOfWork"
```

---

## Final state

- Every publisher command (3 invoicing, 3 expense) and its GL handler run in one
  `platform.UnitOfWork` transaction; a `PeriodClosedError` rolls back the whole
  command — no ghost rows.
- MCP returns a structured `{"status": "rejected", ...}`; web flashes the clean
  message; the event bus and the read paths are unchanged.
- After this lands, the held PR #4 (`period-close-state-machine`) can merge on top
  (this branch already contains its commits).
