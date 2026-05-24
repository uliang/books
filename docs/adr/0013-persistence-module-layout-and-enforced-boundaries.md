# Persistence, module layout, and enforced context boundaries

## Persistence

One relational database; **each module owns its tables**. No module reads
another module's tables — cross-context data flows through published events or
a context's query API. **Reporting is the sole exception**: it is the read
model (ADR-0007, ADR-0010) and may join across context tables; invariant 3/4
joins live there.

One transaction per use-case command, wrapping the publisher and its
synchronous handler (ADR-0011), so the tracer acceptance test is atomic.

v1 engine: **SQLite via SQLAlchemy**. One file, zero ops, production-grade at
single-owner scale. SQLAlchemy is the data-access seam, so Postgres is a later
swap, not a rewrite.

## Module layout

```
src/books/
  platform/              # technical infra only: event bus, unit-of-work,
                         # money/currency VO, db session — NO domain concepts
  party/                 # generic
  general_ledger/        # supporting
  invoicing/             # supporting
  expense_management/    # supporting
  bank_reconciliation/   # CORE
  reporting/             # generic (read model)
  interfaces/{web,mcp}/
  __init__.py            # books:main — composition root
```

Each context exposes **only** a thin application API + its published events.
Aggregates and tables are private. There is **no domain shared kernel** — Party
is referenced by `PartyId` + cached name (CONTEXT); `platform/` is plumbing
only.

## Enforcement

`import-linter` contracts in `pyproject.toml`, wired into the existing
pre-commit + pytest gate. Boundary violations fail the build. Table ownership
(runtime SQL, not importable) stays convention but is contained to the single
Reporting carve-out, keeping the unenforced surface tiny.

Considered and rejected: convention + code review only. In a solo
owner-operated codebase an unenforced boundary erodes silently, making the
entire context map fiction. An enforced contract is the cheapest insurance and
rides the gate that already exists.

## Amendment 2026-05-20 — intra-context persistence subpackage + repository

The original layout placed ORM tables, view dataclasses, and the application
service together in a single `service.py` per context. As contexts grew
(general_ledger reached six tables, a dimensions child table, two
guided-journal templates, and multiple event handlers in one file), this
mixed three distinct concerns — schema, public return types, business logic
talking raw SQLAlchemy — making the file hard to navigate and obscuring the
service's intent.

### Intra-context layout

```
src/books/<context>/
  __init__.py
  events.py                 # published events (unchanged)
  service.py                # application API class + its view dataclasses
                            #   (PostingView, Proposal, … — these are the
                            #   service's signature; co-located with it)
  persistence/
    __init__.py
    tables.py               # ORM models (SQLAlchemy DeclarativeBase rows)
    repository.py           # the context's repository: intent-named methods
                            #   (append_entry, lock_period, unmatched_postings,
                            #    role_code, match, …). Concrete class — no
                            #    Protocol/ABC.
```

The service no longer writes raw `session.execute(select(...))` — it calls
intent-named repository methods that read as business logic. SQLAlchemy
remains the data-access seam per the original ADR-0013; the repository names
*what* the context wants from persistence without abstracting *how*.

### Transaction boundary — the repository owns the unit of work

The repository is the **single** persistence touchpoint for its service. The
unit of work belongs to the repository, not to the platform `Database`. A
small base class in `platform/repository.py` provides the UoW machinery so
every context's concrete repository inherits it for free:

```python
# platform/repository.py
class Repository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @contextmanager
    def unit_of_work(self) -> Iterator[Session]:
        session = Session(self._db.engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
```

`platform/db.py` (`Database`) is narrowed to an **engine container**: it
holds the SQLAlchemy engine and runs `create_all`, but no longer exposes
`unit_of_work` to services. Transactions live where the SQL they wrap does
— inside the persistence package, on the repository.

The service holds **only** its repository (`self._repo`) and uses it for
both transactions and operations:

```python
class LedgerService:
    def __init__(self, db: Database, bus: EventBus, ...) -> None:
        self._repo = LedgerRepository(db)   # the only persistence reference
        # ... event subscriptions ...

    def _on_invoice_issued(self, e: InvoiceIssued) -> None:
        with self._repo.unit_of_work() as session:
            ar = self._repo.role_code(session, "ar")
            revenue = self._repo.role_code(session, "revenue")
            self._repo.append_entry(session, on=..., legs=[...])
```

Repository methods take `session` as the first argument and operate against
it — multiple repo calls in one `unit_of_work()` block run in one
transaction, preserving ADR-0011's "one transaction per use-case command"
intent. Repository-owned UoW *per method* was rejected: it would split any
command with two or more repo operations into separate transactions.

### Repository construction

The service constructs its own repository internally
(`self._repo = LedgerRepository(db)` in `__init__`) and does not retain `db`
as an attribute afterwards. The composition root stays unaware of
persistence — it wires contexts, not their internal organs — and the
service's persistence surface is exactly one object. This is consistent with
the composition root's "wiring only, no business logic" role.

### Enforcement: 6th contract

Reporting is the sanctioned cross-context reader, but only through service
APIs (ADR-0013 query API). With persistence now a subpackage, a new
`import-linter` contract makes the "Reporting reads via service, not
persistence" rule explicit:

- type: `forbidden`
- source_modules: `["books.reporting"]`
- forbidden_modules: every context's `<context>.persistence` subpackage

The existing reporting-leaf contract only stops things importing reporting;
it says nothing about what reporting may reach into. The new contract closes
that gap before any silent erosion happens.

### Considered and rejected

- **Flat `tables.py` + `repository.py`** at each context's top level: lighter
  for small contexts (party has one table), but mixes top-level file types and
  loses the visual "here is the persistence surface" grouping as the context
  grows.
- **Single `persistence.py` file**: reintroduces the original "one file
  mixing many concerns" smell.
- **Protocol/ABC + ORM adapter** (full hexagonal): SQLAlchemy is already the
  swap seam in the original ADR-0013 ("Postgres is a later swap, not a
  rewrite"). Layering a protocol on top duplicates the abstraction without
  delivering testability the project doesn't need (tests use real SQLite).
- **DDD aggregate orchestration with pure-object aggregates**: a bigger
  conceptual shift not justified by the named pain (single-owner accounting
  app; the service is the natural unit of behaviour).
- **View dataclasses (`PostingView`, `Proposal`, …) in persistence**: they
  are the service's signature, not row descriptions; moving them inside
  persistence would force the service to import outward through persistence
  to declare its own return types.

## Amendment 2026-05-24 — the command owns the unit of work

The 2026-05-20 amendment put the unit of work on each **per-context
repository**. That quietly broke ADR-0011's "one transaction per use-case
command": a publisher (e.g. `invoicing.issue_invoice`) opened its repo's
session, and the synchronous handler (`general_ledger._on_invoice_issued`)
opened a *second* repo session. The PR #4 live trial exposed the consequence —
issuing an invoice into a closed period left a **ghost invoice** committed in
invoicing with no matching GL posting.

The mechanism, precisely: v1 runs SQLite under a `StaticPool`, so every
repository session shares **one** physical connection. The publisher's session
flushed the invoice, then a *nested* `unit_of_work()` (the party-name resolver)
committed on that shared connection — committing the invoice too — before the
GL handler rejected the post. So "two transactions" was really one connection
with a premature commit.

**The fix:** transaction ownership moves up to a command-scoped
`platform.UnitOfWork` (`platform/unit_of_work.py`). It opens one `Session` per
command and publishes it through a `contextvar`; `current_session()` returns
it. Publisher commands (the three invoicing and three expense commands) open
the `UnitOfWork`; the Ledger's six event handlers pull that session via
`current_session()` instead of opening their own. Repository methods keep their
`session`-first signatures unchanged. The command commits/rolls back exactly
once, so a handler `PeriodClosedError` rolls back the whole command — no ghost
rows.

`Repository.unit_of_work()` is **retained** for read-only/query paths and the
Ledger's self-contained command writes (`soft_close`, `hard_close`,
`write_off`, `create_account`). The rule: *if a command publishes (or its
handler writes), it uses the platform `UnitOfWork`.*

**Constraint that falls out of the shared connection (important):** inside a
command's `UnitOfWork`, do **not** call another context's service method that
opens its own `unit_of_work()` and commits — on the shared `StaticPool`
connection that nested commit would commit the command's pending work
prematurely (the original ghost). Resolve such cross-context reads **before**
opening the command's `UnitOfWork` (e.g. `issue_invoice` resolves the party
name before the `with self._uow()` block). This is a convention today, not an
enforced contract; making `Repository.unit_of_work()` re-entrant (join the
active `UnitOfWork` instead of opening a second session) would harden it and is
a candidate follow-up. The Postgres swap the original ADR anticipates would
also remove the single-connection footgun (separate connections, true separate
transactions), but the platform `UnitOfWork` is the correct structural fix
regardless of engine.
