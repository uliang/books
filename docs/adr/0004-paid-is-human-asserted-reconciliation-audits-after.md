# "Paid" is human-asserted; Reconciliation audits after the fact

The obvious design gates an invoice's "paid" state on bank reconciliation
confirming the cash. We deliberately do **not** do this.

The owner's real process: customer transfers to the bank and sends a transfer
slip; the owner confirms the funds in the bank, *then* marks the invoice paid.
So "paid" already encodes a human confirmation and is **not provisional**.

Bank Reconciliation is therefore the **systematic, auditable replacement for
the owner's error-prone eyeball check**, operating *after* the assertion. A
paid invoice whose bank posting never clears is a high-priority discrepancy
(the owner *claimed* they verified) — surfaced for review, never silently
reverted. The transfer slip is modeled as attachable proof on the invoice
payment to make the audit trail real.

Consequence: "paid" (Invoicing) and "cleared" (Reconciliation) are distinct
states by design; do not collapse them.
