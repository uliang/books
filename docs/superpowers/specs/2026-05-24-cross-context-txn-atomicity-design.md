# Cross-Context Transaction Atomicity — Design

**Date:** 2026-05-24
**Status:** Approved (brainstorming) → ready for plan
**Amends:** ADR-0013 (persistence / transaction ownership), ADR-0011 (synchronous
event integration). No new ADR — this *restores* their stated intent.
**Follows:** the period-close state machine (PR #4, branch
`period-close-state-machine`), whose live trial surfaced the issue. **PR #4 is
held — do not merge until this fix lands.**

## Goal

Make a use-case command and its synchronous event handlers run in **one
transaction**, so that when a handler rejects a write the *entire* command rolls
back — no half-committed records across contexts. This is exactly what ADR-0011
and ADR-0013 already promise; a later refactor silently regressed it.

## Background — why now

The PR #4 live trial (2026-05-24) exercised the new soft-close gate by issuing an
invoice dated into a soft-closed month. The general-ledger gate correctly rejected
the posting (`append_entry` → `may_post` → `ValueError`), **but the invoice had
already been committed** in the invoicing context. Result: a **ghost invoice**
(`invoices://` shows invoice #3, `status: issued`) with **zero** matching GL
postings (no AR, no Revenue). A torn cross-context write.

### Root cause

ADR-0011 states cross-context event dispatch "runs **inside the same transaction**
as the publisher," and ADR-0013 restates it: "One transaction per use-case command,
wrapping the publisher and its synchronous handler … so the tracer acceptance test
is atomic."

The 2026-05-20 amendment to ADR-0013 moved the unit of work onto each **per-context
repository**. Each context's repository opens its own `Session`:

- `invoicing.issue_invoice` opens session **A**, flushes the invoice, then calls
  `bus.publish(InvoiceIssued)`.
- `general_ledger._on_invoice_issued` opens session **B** (a *different*
  transaction) and calls `append_entry`.

The synchronous bus shares the **call stack** but not the **transaction**. A
handler failure in session B does not roll back session A's write. (The same
amendment explicitly rejected per-*method* UoW "because it splits a command into
separate transactions" — the cross-context split is the identical mistake, unnoticed.)

The closed-period gate itself predates PR #4 (it is on `main` from PR #3, where
`append_entry` already raised "period … is closed"). PR #4 only made the gate
soft/`source_kind`-aware — but that turns the everyday "soft-closed January, then
tried to bill into January" flow into a routine trigger for the torn write.

## Desired behaviour

When a command's handler rejects the write (period closed being the live example):

1. **Atomic rollback.** No rows persist in *any* context — verified by asserting
   zero invoice rows **and** zero GL postings.
2. **Clean, structured rejection.** The caller gets an actionable structured result
   (mirroring `hard_close`'s `"blocked"` result), not a raw stack-trace string.

## Approach — a platform `UnitOfWork` object (Approach C)

Transaction ownership moves *up* from the per-context repository to a
**command-scoped platform object** that spans contexts. Chosen over the ambient
re-entrant `unit_of_work()` (Approach A) and explicit session-through-`publish`
(Approach B) for being the most explicit transaction seam and a natural future home
for the persisted-event-log / outbox evolution ADR-0011 leaves open.

### 1. `platform/unit_of_work.py` (new)

The command-scoped transaction: one session, committed exactly once, made available
to handlers via a `contextvar` (task/thread-safe).

```python
from contextvars import ContextVar
from sqlalchemy.orm import Session

_active_session: ContextVar[Session | None] = ContextVar("active_session", default=None)


def current_session() -> Session:
    s = _active_session.get()
    if s is None:
        raise RuntimeError("no active UnitOfWork")
    return s


class UnitOfWork:
    """The command-scoped transaction (ADR-0011/0013): ONE session shared by the
    publisher and its synchronous handlers, committed exactly once."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self.session: Session | None = None
        self._token = None

    def __enter__(self) -> "UnitOfWork":
        self.session = Session(self._db.engine)
        self._token = _active_session.set(self.session)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.session.commit() if exc_type is None else self.session.rollback()
        finally:
            _active_session.reset(self._token)
            self.session.close()
            self.session = None
```

`UnitOfWork` depends only on `platform.Database` — no bus reference (the contextvar
decouples them), no context imports (platform stays plumbing).

### 2. `platform/events.py` — bus dispatches on the active session

```python
def publish(self, event) -> None:
    session = current_session()          # raises if outside a UnitOfWork (fail loud)
    for handler in self._handlers.get(type(event), ()):
        handler(event, session)
```

Handler exceptions propagate **unchanged** so the outermost `UnitOfWork.__exit__`
owns the rollback; the bus never swallows or re-wraps.

### 3. Services — commands open the UoW; handlers receive the session

A writing service is injected a `unit_of_work` factory at the composition root
(`lambda: UnitOfWork(db)`), since the command transaction is no longer derived from
the service's own repository.

```python
# invoicing/service.py — command
def issue_invoice(self, ...):
    with self._uow() as uow:
        row = self._repo.add(uow.session, ...)
        self._bus.publish(InvoiceIssued(...))     # GL handler joins uow.session
        return Invoice(id=row.id, number=row.number)

# general_ledger/service.py — handler
def _on_invoice_issued(self, e: InvoiceIssued, session: Session) -> None:
    self._repo.append_entry(session, ...)          # same transaction
```

Repository methods keep their intent-named, `session`-first signatures **unchanged**
(`append_entry(session, …)`, `add(session, …)`); only the *ownership* of the session
moves.

### 4. Scope rule — reads keep their lightweight path

`Repository.unit_of_work()` stays for **read-only / query** service methods (single
context, no events). The platform `UnitOfWork` is for **write / command** paths.
Rule: *if it publishes (or its handler writes), it is a command → platform
`UnitOfWork`.* **Within a command, all reads use the command's session — never open a
second one.** This bounds the change to the write side.

## Clean error — typed `PeriodClosedError` + structured result

1. **Domain raises a typed error.** `append_entry` raises
   `PeriodClosedError(period, state, source_kind, on)` instead of a bare
   `ValueError`. It subclasses `ValueError` (existing `except ValueError` sites and
   tests stay safe), carries structured fields and a clean `__str__`, lives in
   `general_ledger/period_lifecycle.py`, and is **re-exported from the context's
   public surface** (`books.general_ledger`) so interfaces import the contract, not
   an internal module.

2. **Atomic rollback does the integrity work** (Section above) — no ghost rows,
   regardless of which command triggered it (invoice, payment, expense all covered).

3. **Interfaces render it structured**, mirroring `hard_close`. The tools whose
   events can land in a closed period (`issue_invoice`, `mark_paid`,
   `adjudicate_settlement`, and the three expense tools) wrap their domain call and,
   on `PeriodClosedError`, return:

   ```python
   {"status": "rejected", "reason": "period_closed",
    "period": "2026-01", "state": "soft",
    "message": "cannot issue invoice dated 2026-01-25: period 2026-01 is soft-closed"}
   ```

   A single shared helper (`rejected_period(e)`) formats this so the tools don't each
   hand-roll the dict. The web interface gets the same typed-error catch at its
   boundary.

## Testing (TDD — tests first)

- **Headline acceptance test** (regression for the torn write): issue an invoice
  dated into a closed period → assert **zero rows in *both* contexts** (no invoice,
  no GL postings) **and** the structured `rejected` result. Real SQLite, full
  command path.
- **`UnitOfWork` unit tests:** commit-on-success (publisher + handler writes both
  persist); **rollback-on-handler-failure** (a raising handler discards the
  publisher's write — the core fix); contextvar reset (after a command,
  `current_session()` raises; sequential commands don't leak); `publish()` outside a
  UoW raises `RuntimeError`.
- **Bus test:** `publish` passes the active session to handlers; handler exceptions
  propagate unchanged.
- **Update existing tests:** period-closed assertions move from bare `ValueError`
  text → `PeriodClosedError` (still a `ValueError` subclass; message text changes).

## ADR amendments

- **ADR-0013** — new amendment (2026-05-24): transaction ownership moves from the
  per-context repository up to a command-scoped platform `UnitOfWork`; repositories
  operate on the provided session. Supersedes the 2026-05-20 "repository owns the
  UoW" rule *for write paths* (reads retain `Repository.unit_of_work()`).
- **ADR-0011** — short note: the synchronous bus realizes "dispatch inside the same
  transaction" by carrying the active session (contextvar) and dispatching
  `(event, session)` — the guarantee the 2026-05-20 change had silently regressed.

## Boundary / import-linter

No new cross-context imports: handlers still touch only their own repository; the
session passed around is a generic SQLAlchemy `Session`, not a context type.
`platform/unit_of_work.py` and the bus import only within `platform`. Interfaces
importing `PeriodClosedError` from `books.general_ledger`'s public surface is
consistent with interfaces already depending on contexts. The 6 existing contracts
must still pass.

## Out of scope

- The ghost invoice #3 already in `books.db` — throwaway trial data the owner will
  clear; not a migration concern.
- StaticPool's single physical connection under *true* concurrency — pre-existing;
  the contextvar gives logical (per-task) isolation, but two genuinely concurrent
  commands still share one connection. Acceptable for a single-owner app; documented
  as a future hardening, not fixed here.
- The reconcile / statement-match clearing path (no MCP tool today) — unrelated.

## Files touched

- **new:** `src/books/platform/unit_of_work.py`
- `src/books/platform/events.py`
- `src/books/general_ledger/service.py`, `period_lifecycle.py`,
  `persistence/repository.py`, and the public re-export of `PeriodClosedError`
- `src/books/invoicing/service.py`
- `src/books/expense_management/service.py`
- `src/books/__init__.py` (wire the `unit_of_work` factory into writing services)
- `src/books/interfaces/mcp/tools/invoicing.py`, `tools/expense.py`, + the shared
  `rejected_period` helper
- web interface boundary catch
- `docs/adr/0011-*.md`, `docs/adr/0013-*.md`
- tests (new + updated per above)
