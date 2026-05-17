# Multi-currency: MYR functional, realized-only FX

Functional currency is **MYR** (single entity, single functional currency).
Invoices may be issued in a **transaction currency** (e.g. SGD) with a
manually-entered booking rate at issue — no FX rate feed in v1. `Money`
is a pervasive `(amount, currency)` value object, not a scalar.

FX gain/loss is recognized **only at settlement** (realized), from the actual
MYR banked, posted to a dedicated P&L FX account. **Period-end revaluation of
open foreign AR is out of v1** — it would materially complicate both the
Ledger and the core Reconciliation model.

A foreign-currency invoice that settles for less MYR than its booked carrying
value is **ambiguous** — underpayment vs adverse FX cannot be determined from
the bank line. The system presents the SGD/MYR picture and the human
adjudicates "settled in full" vs "partial / still owed"; it is never
auto-resolved.

Consequence: choosing period-end revaluation later reopens Ledger and
Reconciliation; the realized-only choice is what keeps the core domain
tractable.
