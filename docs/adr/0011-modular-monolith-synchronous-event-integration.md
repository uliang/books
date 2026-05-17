# Modular monolith with in-process synchronous event integration

The system is one Python process, one deployable, one database. Bounded
contexts are **package boundaries** (`src/books/<context>/`), enforced in the
import graph — not network boundaries. MCP and web are two entrypoints into the
same process.

Contexts integrate by **in-process synchronous domain-event dispatch**:
Invoicing publishes `InvoiceIssued` / `PaymentRecorded`; the Ledger registers
handlers that translate them into postings; dispatch runs **inside the same
transaction** as the publisher. The publisher depends only on "publish an
event" and never names the Ledger — honoring the upstream/downstream direction
in CONTEXT.

Consequences:

- The tracer acceptance test is a **single atomic assertion**, not an
  eventual-consistency problem.
- Bounded contexts are real as **module** boundaries; the discipline lives in
  enforced import rules, not in the network.

Considered and rejected:

- **Separate services.** Buys nothing for a single-owner self-hosted app;
  would turn the reconciliation tie-out into a distributed-consistency problem
  for no benefit.
- **Direct synchronous calls** between contexts. Inverts the dependency arrow
  the domain model is explicit about (Ledger is event-fed, downstream).
- **Persisted event log / async handlers now.** Attractive for accounting
  auditability and replay, but not tracer-essential. The synchronous bus can
  later gain persistence **without changing the publish/subscribe contract**
  (same events), so this is deferred, not foreclosed.
