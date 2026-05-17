# Statement import is an anti-corruption layer with retained raw evidence

Bank statement import is an explicit ACL, not direct parsing into the domain:

- The **raw imported artifact is retained and content-hashed** as the
  *primary* external evidence. The parsed `BankStatement` is a derived,
  replaceable interpretation. This parallels the transfer slip — external proof
  kept as audit evidence (CONTEXT).
- A **parser port** normalizes bank-specific format into the canonical
  `BankStatement`/`StatementLine`. v1 ships exactly one CSV adapter behind the
  port; a new bank format later is a new adapter, never a core change. The core
  never sees a bank's CSV quirks.
- **Footing + parse validation happen at the boundary** (ADR-0014:
  `opening + Σ lines = closing`). Malformed or non-footing external data is
  rejected before it can become a domain aggregate.
- The content hash doubles as the **idempotency key** — re-importing the same
  file is detected by construction.

Considered and rejected: parse the CSV straight into domain objects and
discard the file. Simpler, but when a reconciling item is later disputed the
raw statement is gone and the only "evidence" is our own interpretation —
circular and worthless for a control whose entire value proposition is
*trustworthy, auditable* books. The parsed form must remain falsifiable
against the original, exactly as the transfer slip is for a payment. Building a
multi-bank framework now is the opposite over-reach (YAGNI) — one adapter
behind a port is the balance.
