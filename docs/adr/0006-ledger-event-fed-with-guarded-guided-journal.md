# Ledger is event-fed; one guarded guided-journal path

Humans rarely write to the General Ledger directly. Operational flows
(invoices, expenses, contractor payments, card settlements) are **captured in
their own contexts** and the Ledger consumes events to produce postings. This
keeps high-volume, error-prone bookkeeping out of free-hand journaling.

There is exactly **one narrow, role-restricted direct-to-ledger route — the
guided-journal path** — for things that genuinely must be authored directly:
opening balances, corrections, period-closing entries, owner draws, capital
injections, and statement-only items (e.g. bank fees) routed from Bank
Reconciliation. These are pre-validated templates, not arbitrary journal
access.

Consequence: a system with no direct ledger path can't even be initialized;
this ADR records that the path exists *by design* and is deliberately the only
one.
