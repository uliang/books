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
