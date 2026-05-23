# Period-Close State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the period close `kind` ("soft"/"hard") real behaviour by modelling a period's close status as an explicit state machine, so soft and hard close gate different actions (ADR-0008/0009, amended).

**Architecture:** A pure `period_lifecycle` policy module in the Ledger owns the state enum, the `may_post`/`may_reconcile` matrix, and the transitions. `append_entry` and the Bank Reconciliation clearance write both consult it; the cross-context guard is injected as a plain boolean callable at the composition root.

**Tech Stack:** Python 3.13, `uv`, SQLAlchemy, FastMCP, pytest. Test with `uv run pytest --timeout=60`; lint with `uv run ruff check src tests`; boundaries with `uv run lint-imports`.

**Spec:** `docs/superpowers/specs/2026-05-23-period-close-state-machine-design.md`
**Domain references:** `tests/test_increment_2_soft_close_carry_forward.py`, `tests/test_increment_4_hard_close_gate.py`.

## Key facts (already built — do not reimplement)

- `_PeriodClose` table: `period` PK (`YYYY-MM`), `kind` ("soft"/"hard"). No row = OPEN.
- `LedgerRepository.append_entry(session, *, on, narrative, source_kind, source_id, legs)` is the single posting chokepoint. Event handlers pass `source_kind` = the event name (InvoiceIssued, PaymentRecorded, SettlementAdjudicated, OwnerPaidExpenseRecorded, ContractorPaid, OwnerReimbursed); `write_off` and the year-end sweep pass `source_kind="GuidedJournal"`.
- `LedgerService.hard_close(year)` blocks on injected `year_end_blockers`, sweeps net P&L → Owner's Equity (a GuidedJournal dated Dec 31), then locks all 12 months. `soft_close(period)` locks one month.
- `ReportingService.year_end_blockers(year)` returns `list[ReconcilingItem]{ref, amount, age_days, classification}`; constants `TIMING_DIFFERENCE`/`STALE_EXCEPTION` in `reporting/service.py`.
- `BankReconciliationService.confirm_match(statement_line_ref, ledger_posting_ref)` is the sole clearance write (ADR-0015).
- Sign convention: a credit balance is negative minor units. Revenue 1500 → `account_balance("Revenue") == Money.myr(-1500_00)` before close, `0` after; Owner's Equity receives `Money.myr(-1500_00)`.
- `period_of(d: date) -> "YYYY-MM"` lives in `general_ledger/persistence/tables.py` and is already imported in `repository.py`.

## File Structure

- **Create** `src/books/general_ledger/period_lifecycle.py` — pure policy (state, matrix, transitions).
- **Create** `tests/test_period_lifecycle.py` — pure unit tests.
- **Modify** `src/books/general_ledger/persistence/repository.py` — `period_state`, `posting_period_state`, `append_entry` gate, `lock_period` upgrade; drop dead `is_period_locked`.
- **Modify** `src/books/general_ledger/service.py` — `soft_close` reject-on-hard, `hard_close` already-closed guard, `posting_is_reconcilable` read, `PeriodLockView` docstring.
- **Modify** `src/books/reporting/service.py` — `year_end_blockers` → all-uncleared, classified by age.
- **Modify** `src/books/bank_reconciliation/service.py` — injected `posting_is_reconcilable`, `confirm_match` guard.
- **Modify** `src/books/__init__.py` — wire `posting_is_reconcilable`.
- **Modify** `src/books/interfaces/mcp/tools/closing.py` — `hard_close` tool blocker dict includes `classification`.
- **Modify** `docs/adr/0008-fiscal-period-and-two-tier-close.md`, `docs/adr/0009-close-clearance-contract.md`.
- **Modify** `tests/test_mcp_period_close.py`, `tests/test_period_lifecycle.py`, plus new domain tests in `tests/`.

---

### Task 1: The pure `period_lifecycle` policy module

**Files:**
- Create: `src/books/general_ledger/period_lifecycle.py`
- Test: `tests/test_period_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_period_lifecycle.py`:

```python
"""Pure unit tests for the period-close lifecycle policy (ADR-0008/0009)."""

from __future__ import annotations

import pytest

from books.general_ledger.period_lifecycle import (
    PeriodState,
    may_post,
    may_reconcile,
    on_hard_close,
    on_soft_close,
)


def test_open_accepts_any_posting():
    assert may_post(PeriodState.OPEN, "InvoiceIssued")
    assert may_post(PeriodState.OPEN, "GuidedJournal")


def test_soft_accepts_only_guided_journal():
    assert may_post(PeriodState.SOFT, "GuidedJournal")
    assert not may_post(PeriodState.SOFT, "InvoiceIssued")
    assert not may_post(PeriodState.SOFT, "PaymentRecorded")


def test_hard_accepts_nothing():
    assert not may_post(PeriodState.HARD, "GuidedJournal")
    assert not may_post(PeriodState.HARD, "InvoiceIssued")


def test_reconciliation_blocked_only_when_hard():
    assert may_reconcile(PeriodState.OPEN)
    assert may_reconcile(PeriodState.SOFT)
    assert not may_reconcile(PeriodState.HARD)


def test_soft_close_transition():
    assert on_soft_close(PeriodState.OPEN) is PeriodState.SOFT
    assert on_soft_close(PeriodState.SOFT) is PeriodState.SOFT
    with pytest.raises(ValueError, match="hard-closed"):
        on_soft_close(PeriodState.HARD)


def test_hard_close_transition():
    assert on_hard_close(PeriodState.OPEN) is PeriodState.HARD
    assert on_hard_close(PeriodState.SOFT) is PeriodState.HARD
    with pytest.raises(ValueError, match="already hard-closed"):
        on_hard_close(PeriodState.HARD)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_period_lifecycle.py -v`
Expected: FAIL — `ModuleNotFoundError: books.general_ledger.period_lifecycle`.

- [ ] **Step 3: Create the module**

Create `src/books/general_ledger/period_lifecycle.py`:

```python
"""Period-close lifecycle (ADR-0008 / ADR-0009, amended 2026-05-23).

A period (YYYY-MM) moves Open → Soft → Hard, monotonically; Hard is terminal.
This pure module is the single home for what each state permits — no I/O, so
the rules are unit-testable in isolation. The Ledger's append_entry and the
Bank Reconciliation clearance write both consult it.
"""

from __future__ import annotations

from enum import Enum

GUIDED_JOURNAL = "GuidedJournal"


class PeriodState(Enum):
    OPEN = "open"
    SOFT = "soft"
    HARD = "hard"


def may_post(state: PeriodState, source_kind: str) -> bool:
    """May an entry with this source_kind post into a period in `state`?

    Open accepts anything; Soft accepts only the guarded guided-journal
    correction channel (ADR-0006); Hard accepts nothing (immutable).
    """
    if state is PeriodState.OPEN:
        return True
    if state is PeriodState.SOFT:
        return source_kind == GUIDED_JOURNAL
    return False


def may_reconcile(state: PeriodState) -> bool:
    """May a clearance match be confirmed against a posting in `state`?
    Forbidden once the period is hard-closed and fully settled."""
    return state is not PeriodState.HARD


def on_soft_close(state: PeriodState) -> PeriodState:
    """Transition for soft_close. Open/Soft → Soft (idempotent); Hard rejects."""
    if state is PeriodState.HARD:
        raise ValueError("cannot soft-close a hard-closed period")
    return PeriodState.SOFT


def on_hard_close(state: PeriodState) -> PeriodState:
    """Transition for hard_close. Open/Soft → Hard; Hard rejects (already closed)."""
    if state is PeriodState.HARD:
        raise ValueError("period already hard-closed")
    return PeriodState.HARD
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_period_lifecycle.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/books/general_ledger/period_lifecycle.py tests/test_period_lifecycle.py
git commit -m "feat(general_ledger): period-close lifecycle policy module"
```

---

### Task 2: `append_entry` gates via the policy

**Files:**
- Modify: `src/books/general_ledger/persistence/repository.py` (add `period_state`; rewrite the `append_entry` guard ~line 108-110; imports)
- Test: `tests/test_period_state_gating.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_period_state_gating.py`:

```python
"""append_entry gates by (period state, source_kind): a soft-closed month
admits a guarded guided-journal correction but rejects casual economic
entries; the year-end sweep into a soft-closed December therefore works."""

from __future__ import annotations

from datetime import date

import pytest

from books import create_app
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


def test_guided_journal_correction_allowed_into_soft_month():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1, party_id=acme.id, amount=Money.myr(1000_00), issued_on=date(2026, 1, 10)
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 1, 28))
    (bank_posting,) = app.ledger.postings_for(code="Bank")

    app.ledger.soft_close("2026-01")

    # A casual economic entry into soft January is rejected...
    with pytest.raises(ValueError, match="2026-01"):
        app.invoicing.issue_invoice(
            number=2, party_id=acme.id, amount=Money.myr(500_00), issued_on=date(2026, 1, 15)
        )
    # ...but a guarded guided-journal write-off into soft January is allowed.
    app.ledger.write_off(posting_ref=bank_posting.ref, on=date(2026, 1, 31))
    assert app.ledger.account_balance(code="Write-off") == Money.myr(1000_00)
    assert app.ledger.account_balance(code="Bank") == Money.myr(0)


def test_soft_closing_december_then_hard_close_succeeds():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    # Accrued revenue only — no bank posting, so nothing blocks the close.
    app.invoicing.issue_invoice(
        number=1, party_id=acme.id, amount=Money.myr(1500_00), issued_on=date(2026, 2, 1)
    )

    app.ledger.soft_close("2026-12")  # the LAST month, soft-closed first

    # The Dec-31 P&L sweep is a guided journal; soft December must admit it.
    app.ledger.hard_close(2026)
    assert app.ledger.account_balance(code="Owner's Equity") == Money.myr(-1500_00)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_period_state_gating.py -v`
Expected: FAIL — `write_off` into soft January raises today (blanket lock), and the soft-December sweep raises `period 2026-12 is closed`.

- [ ] **Step 3: Add the `period_state` query and gate `append_entry`**

In `src/books/general_ledger/persistence/repository.py`, add to the imports near the top (the `from books.general_ledger.persistence.tables import (...)` block stays; add a new import line after it):

```python
from books.general_ledger.period_lifecycle import PeriodState, may_post
```

Add this query method right after `is_period_locked` (~line 147):

```python
    def period_state(self, session: Session, period: str) -> PeriodState:
        """The close state of a period: OPEN (no lock), SOFT, or HARD."""
        row = session.execute(
            select(_PeriodClose).where(_PeriodClose.period == period)
        ).scalar_one_or_none()
        if row is None:
            return PeriodState.OPEN
        return PeriodState.SOFT if row.kind == "soft" else PeriodState.HARD
```

Replace the guard inside `append_entry` (currently):

```python
        period = period_of(on)
        if self.is_period_locked(session, period):
            raise ValueError(f"period {period} is closed: cannot post on {on}")
```

with:

```python
        period = period_of(on)
        state = self.period_state(session, period)
        if not may_post(state, source_kind):
            raise ValueError(
                f"period {period} is {state.value}-closed: "
                f"cannot post {source_kind} on {on}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_period_state_gating.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the affected existing suites**

Run: `uv run pytest tests/test_increment_2_soft_close_carry_forward.py tests/test_increment_4_hard_close_gate.py tests/test_mcp_period_close.py tests/test_mcp_errors.py -v`
Expected: PASS (the new error message still contains the period and "closed", which those tests match on).

- [ ] **Step 6: Commit**

```bash
git add src/books/general_ledger/persistence/repository.py tests/test_period_state_gating.py
git commit -m "feat(general_ledger): gate append_entry by period state + source_kind"
```

---

### Task 3: Strengthen the hard-close gate to "any uncleared"

**Files:**
- Modify: `src/books/reporting/service.py` (`year_end_blockers`)
- Test: `tests/test_hard_close_gate_strengthened.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_hard_close_gate_strengthened.py`:

```python
"""The amended hard-close gate (ADR-0009): ANY uncleared bank posting blocks,
not just stale ones. A recent (timing-difference) uncleared item now blocks
too; its classification survives only as triage."""

from __future__ import annotations

from datetime import date

import pytest

from books import create_app
from books.platform.money import Money


def test_recent_uncleared_posting_blocks_hard_close():
    app = create_app("sqlite://")  # stale_after_days defaults to 30
    acme = app.party.register_party(name="Acme", role="customer")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")

    # A RECENT uncleared receipt (Dec 20) — only 11 days old at year-end, so a
    # timing difference under the old rule, which would NOT have blocked.
    inv = app.invoicing.issue_invoice(
        number=1, party_id=acme.id, amount=Money.myr(1000_00), issued_on=date(2026, 12, 15)
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 12, 20))

    with pytest.raises(ValueError, match="blocked"):
        app.ledger.hard_close(2026)

    (blocker,) = app.reporting.year_end_blockers(2026)
    assert blocker.classification == "timing_difference"  # triage label, still blocks
    assert blocker.age_days == 11
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hard_close_gate_strengthened.py -v`
Expected: FAIL — today the recent item is *not* a blocker (age 11 ≤ 30), so `hard_close` succeeds and the `pytest.raises` is not triggered.

- [ ] **Step 3: Rewrite `year_end_blockers`**

In `src/books/reporting/service.py`, replace the body of `year_end_blockers` with:

```python
    def year_end_blockers(self, year: int) -> list[ReconcilingItem]:
        """Every uncleared bank posting standing in the way of the annual hard
        close (ADR-0009, amended): any posting neither matched to a statement
        nor written off blocks, regardless of age. Each carries a timing/stale
        classification by age purely as owner-facing triage — the
        classification no longer gates."""
        year_end = date(year, 12, 31)
        matched = self._recon.matched_posting_refs()
        written_off = self._ledger.written_off_refs()
        blockers: list[ReconcilingItem] = []
        for p in self._ledger.postings_for(code=self._ledger.role_code("bank")):
            if p.ref in matched or p.ref in written_off:
                continue
            age = (year_end - p.date).days
            classification = (
                STALE_EXCEPTION if age > self._stale_after_days else TIMING_DIFFERENCE
            )
            blockers.append(
                ReconcilingItem(
                    ref=p.ref,
                    amount=p.amount,
                    age_days=age,
                    classification=classification,
                )
            )
        return blockers
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hard_close_gate_strengthened.py tests/test_increment_4_hard_close_gate.py -v`
Expected: PASS (the increment-4 phantom is stale, so it still blocks; the new recent-item case now blocks too).

- [ ] **Step 5: Commit**

```bash
git add src/books/reporting/service.py tests/test_hard_close_gate_strengthened.py
git commit -m "feat(reporting): hard-close gate blocks on any uncleared item"
```

---

### Task 4: Transitions — soft→hard upgrade, reject-on-hard, no double close

**Files:**
- Modify: `src/books/general_ledger/persistence/repository.py` (`lock_period` upgrade; drop dead `is_period_locked`)
- Modify: `src/books/general_ledger/service.py` (`soft_close` reject-on-hard; `hard_close` already-closed guard)
- Test: `tests/test_period_transitions.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_period_transitions.py`:

```python
"""Close-state transitions: hard_close upgrades a soft month to hard (fixing
the January-stays-soft bug); soft_close rejects a hard month; hard_close
rejects a re-run (no double P&L sweep)."""

from __future__ import annotations

from datetime import date

import pytest

from books import create_app
from books.platform.money import Money


def _chart(app):
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(
        code="Owner's Equity", name="Owner's Equity", type="equity"
    )


def test_hard_close_upgrades_soft_month_to_hard():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    app.invoicing.issue_invoice(
        number=1, party_id=acme.id, amount=Money.myr(1500_00), issued_on=date(2026, 2, 1)
    )
    app.ledger.soft_close("2026-01")

    app.ledger.hard_close(2026)

    kinds = {lk.period: lk.kind for lk in app.ledger.locked_periods()}
    assert len(kinds) == 12
    assert all(kind == "hard" for kind in kinds.values())  # January upgraded


def test_soft_close_on_hard_closed_period_is_rejected():
    app = create_app("sqlite://")
    _chart(app)
    app.ledger.hard_close(2026)  # clean books, no blockers
    with pytest.raises(ValueError, match="hard-closed"):
        app.ledger.soft_close("2026-06")


def test_hard_close_twice_is_rejected():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    app.invoicing.issue_invoice(
        number=1, party_id=acme.id, amount=Money.myr(1500_00), issued_on=date(2026, 2, 1)
    )
    app.ledger.hard_close(2026)
    with pytest.raises(ValueError, match="already"):
        app.ledger.hard_close(2026)
    # P&L was swept exactly once.
    assert app.ledger.account_balance(code="Owner's Equity") == Money.myr(-1500_00)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_period_transitions.py -v`
Expected: FAIL — `lock_period` skip-if-exists leaves January `soft`; `soft_close` and a second `hard_close` don't yet reject.

- [ ] **Step 3: Make `lock_period` upgrade-capable and drop dead code**

In `src/books/general_ledger/persistence/repository.py`, replace `lock_period` (currently):

```python
    def lock_period(self, session: Session, period: str, *, kind: str) -> None:
        """Record a period lock (ADR-0009). Idempotent."""
        if not self.is_period_locked(session, period):
            session.add(_PeriodClose(period=period, kind=kind))
```

with:

```python
    def lock_period(self, session: Session, period: str, *, kind: str) -> None:
        """Record or upgrade a period lock (ADR-0009). Inserts a new lock, or
        upgrades an existing soft lock to hard; never downgrades, idempotent on
        a repeat of the same kind."""
        row = session.execute(
            select(_PeriodClose).where(_PeriodClose.period == period)
        ).scalar_one_or_none()
        if row is None:
            session.add(_PeriodClose(period=period, kind=kind))
        elif row.kind == "soft" and kind == "hard":
            row.kind = "hard"
```

Then delete the now-unused `is_period_locked` method (Task 2's `period_state` superseded it; `lock_period` no longer calls it). Verify nothing else references it:

Run: `grep -rn "is_period_locked" src/ tests/`
Expected: no matches after deletion.

- [ ] **Step 4: Add transition guards in the service**

In `src/books/general_ledger/service.py`, add to the lifecycle imports near the top:

```python
from books.general_ledger.period_lifecycle import PeriodState, on_soft_close
```

Replace `soft_close` (currently):

```python
    def soft_close(self, period: str) -> None:
        """Lock ``period`` (YYYY-MM) against new economic entries (ADR-0009).

        Never blocks on uncleared bank postings — clearance is the
        orthogonal axis and is deliberately not consulted here. Idempotent.
        """
        with self._repo.unit_of_work() as session:
            self._repo.lock_period(session, period, kind="soft")
```

with:

```python
    def soft_close(self, period: str) -> None:
        """Lock ``period`` (YYYY-MM) against casual economic entries; guarded
        guided-journal corrections and reconciliation still pass (ADR-0009,
        amended). Never blocks on uncleared items; idempotent on a soft
        period; rejects a period already hard-closed."""
        with self._repo.unit_of_work() as session:
            on_soft_close(self._repo.period_state(session, period))  # rejects HARD
            self._repo.lock_period(session, period, kind="soft")
```

In `hard_close`, add the already-closed guard. Immediately after the existing blocker check raises (the `if blockers:` block) and before `on = date(year, 12, 31)`, the method opens `with self._repo.unit_of_work() as session:`. Add the guard as the first statement inside that `with` block:

```python
        with self._repo.unit_of_work() as session:
            if self._repo.period_state(session, f"{year:04d}-12") is PeriodState.HARD:
                raise ValueError(f"hard close {year}: already closed")
            balances = self._repo.pnl_balances(session)
            # ... rest of the existing body unchanged ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_period_transitions.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/books/general_ledger/persistence/repository.py src/books/general_ledger/service.py tests/test_period_transitions.py
git commit -m "feat(general_ledger): soft->hard upgrade + transition guards"
```

---

### Task 5: MCP ripple — `hard_close` tool surfaces classification

**Files:**
- Modify: `src/books/interfaces/mcp/tools/closing.py` (blocked dict + comment)
- Test: `tests/test_mcp_period_close.py` (append a test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_period_close.py`:

```python
def test_hard_close_blocked_reports_recent_item_as_timing_via_mcp():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    customer = app.party.register_party(name="Acme", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            issued = json.loads(
                (
                    await client.call_tool(
                        "issue_invoice",
                        {
                            "number": 1,
                            "party_id": customer.id,
                            "amount_minor": 1000_00,
                            "currency": "MYR",
                            "issued_on": "2026-12-15",
                        },
                    )
                )
                .content[0]
                .text
            )
            await client.call_tool(
                "mark_paid",
                {"invoice_id": issued["invoice_id"], "paid_on": "2026-12-20"},
            )
            blocked = json.loads(
                (await client.call_tool("hard_close", {"year": 2026}))
                .content[0]
                .text
            )
            assert blocked["status"] == "blocked"
            assert len(blocked["blockers"]) == 1
            assert blocked["blockers"][0]["classification"] == "timing_difference"

    run(scenario())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_period_close.py::test_hard_close_blocked_reports_recent_item_as_timing_via_mcp -v`
Expected: FAIL — the tool's blocked dict has no `classification` key (`KeyError`).

- [ ] **Step 3: Add `classification` to the blocked dict**

In `src/books/interfaces/mcp/tools/closing.py`, replace the blocked-branch (the comment plus the return) inside `hard_close` — currently:

```python
        blockers = books.reporting.year_end_blockers(year)
        if blockers:
            # year_end_blockers returns only stale exceptions (timing
            # differences don't block, ADR-0009), so classification is
            # constant here and omitted; the year-end-blockers:// resource
            # carries it for the general pre-flight view.
            return {
                "status": "blocked",
                "blockers": [
                    {
                        "ref": b.ref,
                        "amount_minor": b.amount.minor_units,
                        "currency": b.amount.currency.value,
                        "age_days": b.age_days,
                    }
                    for b in blockers
                ],
            }
```

with:

```python
        blockers = books.reporting.year_end_blockers(year)
        if blockers:
            # Any uncleared bank posting blocks (ADR-0009 amended); each
            # carries its timing/stale classification so the agent can guide
            # the owner (chase a late statement vs write off a phantom).
            return {
                "status": "blocked",
                "blockers": [
                    {
                        "ref": b.ref,
                        "amount_minor": b.amount.minor_units,
                        "currency": b.amount.currency.value,
                        "age_days": b.age_days,
                        "classification": b.classification,
                    }
                    for b in blockers
                ],
            }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_period_close.py -v`
Expected: PASS (all period-close MCP tests).

- [ ] **Step 5: Commit**

```bash
git add src/books/interfaces/mcp/tools/closing.py tests/test_mcp_period_close.py
git commit -m "feat(mcp): hard_close blocked result carries classification"
```

---

### Task 6: Cross-context — freeze reconciliation on hard-closed periods

**Files:**
- Modify: `src/books/general_ledger/persistence/repository.py` (`posting_period_state`)
- Modify: `src/books/general_ledger/service.py` (`posting_is_reconcilable`)
- Modify: `src/books/bank_reconciliation/service.py` (injected guard on `confirm_match`)
- Modify: `src/books/__init__.py` (wire it)
- Test: `tests/test_reconciliation_freeze.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_reconciliation_freeze.py`:

```python
"""Reconciliation is forbidden on a hard-closed period (ADR-0009 amended): a
late statement cannot retroactively clear a posting in a closed year."""

from __future__ import annotations

from datetime import date

import pytest

from books import create_app
from books.platform.db import Database
from books.bank_reconciliation.service import BankReconciliationService
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


def test_confirm_match_guard_rejects_unreconcilable_posting():
    # Unit-level: the injected reader says no → confirm_match raises.
    svc = BankReconciliationService(
        Database(),
        bank_postings=lambda account: [],
        posting_is_reconcilable=lambda _ref: False,
    )
    with pytest.raises(ValueError, match="hard-closed"):
        svc.confirm_match(statement_line_ref=1, ledger_posting_ref=1)


def test_posting_is_reconcilable_flips_with_period_state():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1, party_id=acme.id, amount=Money.myr(1000_00), issued_on=date(2026, 1, 10)
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 3, 1))
    (bank_posting,) = app.ledger.postings_for(code="Bank")

    assert app.ledger.posting_is_reconcilable(bank_posting.ref) is True  # OPEN

    # Resolve the phantom so the year can hard-close, then close it.
    app.ledger.write_off(posting_ref=bank_posting.ref, on=date(2026, 12, 31))
    app.ledger.hard_close(2026)

    assert app.ledger.posting_is_reconcilable(bank_posting.ref) is False  # HARD


def test_confirm_match_rejected_end_to_end_after_hard_close():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1, party_id=acme.id, amount=Money.myr(1000_00), issued_on=date(2026, 1, 10)
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 3, 1))
    (bank_posting,) = app.ledger.postings_for(code="Bank")
    app.ledger.write_off(posting_ref=bank_posting.ref, on=date(2026, 12, 31))
    app.ledger.hard_close(2026)

    # A late statement shows the March transaction; matching it post-close fails.
    app.bank_reconciliation.import_statement(
        account="Bank",
        period="2026-03",
        opening=Money.myr(0),
        closing=Money.myr(1000_00),
        raw="date,amount,description\n2026-03-01,1000.00,ACME TRANSFER\n",
        fmt="csv",
    )
    (line,) = app.bank_reconciliation.statement_lines(account="Bank", period="2026-03")
    with pytest.raises(ValueError, match="hard-closed"):
        app.bank_reconciliation.confirm_match(
            statement_line_ref=line.ref, ledger_posting_ref=bank_posting.ref
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reconciliation_freeze.py -v`
Expected: FAIL — `confirm_match` has no guard / `posting_is_reconcilable` does not exist.

- [ ] **Step 3: Add `posting_period_state` to the repository**

In `src/books/general_ledger/persistence/repository.py`, add after `get_posting` (~line 262):

```python
    def posting_period_state(
        self, session: Session, posting_ref: int
    ) -> PeriodState | None:
        """The close state of the period a posting falls in, or None if the
        posting does not exist."""
        posting = session.get(_Posting, posting_ref)
        if posting is None:
            return None
        return self.period_state(session, period_of(posting.date))
```

- [ ] **Step 4: Add `posting_is_reconcilable` to the Ledger service**

In `src/books/general_ledger/service.py`, extend the lifecycle import added in Task 4 to also bring in `may_reconcile`:

```python
from books.general_ledger.period_lifecycle import (
    PeriodState,
    may_reconcile,
    on_soft_close,
)
```

Add this read method to `LedgerService`, after `written_off_refs` (~line 362):

```python
    def posting_is_reconcilable(self, posting_ref: int) -> bool:
        """Whether a clearance match may still be confirmed against this
        posting: true unless its period is hard-closed (ADR-0009 amended).
        Bank Reconciliation consults this before confirm_match. An unknown
        ref returns True so confirm_match surfaces its own error."""
        with self._repo.unit_of_work() as session:
            state = self._repo.posting_period_state(session, posting_ref)
        return True if state is None else may_reconcile(state)
```

- [ ] **Step 5: Guard `confirm_match`**

In `src/books/bank_reconciliation/service.py`, the constructor currently reads:

```python
    def __init__(
        self,
        db: Database,
        bank_postings: Callable[[str], list[PostingView]],
    ) -> None:
        self._repo = BankReconciliationRepository(db)
        self._bank_postings = bank_postings
```

Change it to accept an injected, default-permissive guard (mirroring how `LedgerService` defaults `year_end_blockers`):

```python
    def __init__(
        self,
        db: Database,
        bank_postings: Callable[[str], list[PostingView]],
        posting_is_reconcilable: Callable[[int], bool] = lambda _ref: True,
    ) -> None:
        self._repo = BankReconciliationRepository(db)
        self._bank_postings = bank_postings
        self._posting_is_reconcilable = posting_is_reconcilable
```

Then add the guard as the first statement of `confirm_match` (before the `with self._repo.unit_of_work()` block):

```python
    def confirm_match(self, statement_line_ref: int, ledger_posting_ref: int) -> None:
        if not self._posting_is_reconcilable(ledger_posting_ref):
            raise ValueError(
                f"cannot reconcile posting {ledger_posting_ref}: "
                "its period is hard-closed"
            )
        with self._repo.unit_of_work() as session:
            # ... rest unchanged ...
```

- [ ] **Step 6: Wire it at the composition root**

In `src/books/__init__.py`, the `recon` construction currently reads:

```python
    recon = BankReconciliationService(
        db, bank_postings=lambda account: ledger.postings_for(code=account)
    )
```

Change it to inject the reader (the Ledger is already defined above this line):

```python
    recon = BankReconciliationService(
        db,
        bank_postings=lambda account: ledger.postings_for(code=account),
        posting_is_reconcilable=lambda ref: ledger.posting_is_reconcilable(ref),
    )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_reconciliation_freeze.py tests/test_increment_2_soft_close_carry_forward.py tests/test_bank_reconciliation.py tests/test_reporting.py -v`
Expected: PASS — the freeze tests pass; increment-2 still clears its *soft*-January posting (reconciliation allowed on soft); the direct-construction tests still work via the default no-op guard.

- [ ] **Step 8: Commit**

```bash
git add src/books/general_ledger/persistence/repository.py src/books/general_ledger/service.py src/books/bank_reconciliation/service.py src/books/__init__.py tests/test_reconciliation_freeze.py
git commit -m "feat: freeze reconciliation on hard-closed periods"
```

---

### Task 7: Docs — amend ADR-0008/0009 and correct the `PeriodLockView` docstring

**Files:**
- Modify: `docs/adr/0008-fiscal-period-and-two-tier-close.md`
- Modify: `docs/adr/0009-close-clearance-contract.md`
- Modify: `src/books/general_ledger/service.py` (`PeriodLockView` docstring)

- [ ] **Step 1: Correct the `PeriodLockView` docstring**

In `src/books/general_ledger/service.py`, the `PeriodLockView` dataclass docstring currently says:

```python
    """A closed period and its kind (soft/hard) — a read view, no behaviour."""
```

Replace it with:

```python
    """A closed period and its kind. The kind now carries behaviour (see
    ``period_lifecycle``): soft permits guarded guided-journal corrections and
    reconciliation; hard permits neither."""
```

- [ ] **Step 2: Append an amendment to ADR-0008**

Add to the end of `docs/adr/0008-fiscal-period-and-two-tier-close.md`:

```markdown

## Amendment (2026-05-23): the soft/hard distinction is enforced

Originally `kind` was descriptive only — soft and hard locks blocked postings
identically. The distinction is now realized as a period state machine
(`general_ledger/period_lifecycle.py`): **soft** permits guarded guided-journal
corrections (with a reason, the channel reconciliation uses to fix a discovered
error) and bank reconciliation; **hard** permits nothing — the year is immutable.
The annual hard close upgrades any soft month to hard and may sweep up
never-soft-closed months directly (monthly soft-close is a convenience, not a
required gate).
```

- [ ] **Step 3: Append an amendment to ADR-0009**

Add to the end of `docs/adr/0009-close-clearance-contract.md`:

```markdown

## Amendment (2026-05-23): full reconciliation gates the hard close

The "timing difference carries across the boundary and does not block" provision
is removed. A late bank statement shares its transaction's date, so it reconciles
the original period once it arrives — you wait for it, reconcile, then close. The
annual hard close therefore requires **full** reconciliation: every bank posting
must be matched to a statement or written off; *any* uncleared item blocks,
regardless of age. Clearance remains exempt from the *soft* lock but is
**forbidden under hard** (a hard-closed period is settled — `confirm_match`
refuses it). The timing/stale classification survives only as mid-year reporting
triage, no longer as a gate.
```

- [ ] **Step 4: Verify the suite is unaffected**

Run: `uv run pytest tests/test_period_locks_read.py -v`
Expected: PASS (docstring change is inert).

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0008-fiscal-period-and-two-tier-close.md docs/adr/0009-close-clearance-contract.md src/books/general_ledger/service.py
git commit -m "docs: amend ADR-0008/0009 for the period-close state machine"
```

---

### Task 8: Full-suite gate + final review

**Files:** none (verification only)

- [ ] **Step 1: Whole suite**

Run: `uv run pytest --timeout=60`
Expected: PASS (all prior tests + the new lifecycle, gating, gate-strengthen, transitions, MCP, and freeze tests).

- [ ] **Step 2: Lint**

Run: `uv run ruff check src tests`
Expected: no errors.

- [ ] **Step 3: Boundary contracts**

Run: `uv run lint-imports`
Expected: `Contracts: 6 kept, 0 broken`. (Watch the intra-Ledger import of `period_lifecycle` from `persistence/repository.py` — both live in `books.general_ledger`, so it is an in-context import; if a contract flags it, the policy module is already at the package top level where both the repo and the service may import it.)

- [ ] **Step 4: Final review**

Dispatch a final reviewer over the whole branch diff (`git diff main...HEAD`), then proceed to `superpowers:finishing-a-development-branch`.

---

## Self-Review

**Spec coverage:**
- Lifecycle (Open→Soft→Hard, shortcut, terminal) → Tasks 1, 4. ✓
- Pure policy module + matrix → Task 1. ✓
- `append_entry` gates by (state, source_kind) → Task 2. ✓
- Strengthened gate (any uncleared) + classification demoted → Task 3. ✓
- soft→hard upgrade (January fix), reject-on-hard, no double sweep → Task 4. ✓
- MCP ripple (classification in blocked dict) → Task 5. ✓
- Cross-context freeze (`posting_is_reconcilable` + `confirm_match` guard + wiring) → Task 6. ✓
- ADR amendments + docstring → Task 7. ✓
- Latent December-soft-then-hard regression → Task 2 (`test_soft_closing_december_then_hard_close_succeeds`). ✓
- Classification kept in `reconciliation_report` → unchanged by design; Task 3 only touches `year_end_blockers`. ✓

**Placeholder scan:** No TBD/TODO/"similar to"; every code step shows complete before/after. ✓

**Type consistency:** `PeriodState`, `may_post`, `may_reconcile`, `on_soft_close`, `on_hard_close` defined in Task 1 and used with identical signatures in Tasks 2, 4, 6. `period_state`/`posting_period_state` (repo) and `posting_is_reconcilable` (service) names consistent across Tasks 2, 4, 6. The injected callable is `posting_is_reconcilable` everywhere (service method, constructor param, composition-root lambda). Blocker dict keys match between Task 5's tool and Task 3's `ReconcilingItem`. ✓

**Backward-compat checks baked in:** new `append_entry` message still contains the period + "closed" (Task 2 Step 5 reruns the matching tests); `BankReconciliationService`'s new param defaults to a no-op so the two direct-construction tests keep working (Task 6); existing stale-item close tests stay green because "any uncleared" still includes stale (Tasks 3, 5).
