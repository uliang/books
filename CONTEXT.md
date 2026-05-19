# books — Self-service accounting for a small business

A double-entry accounting system for a single owner-operated business. Most
cash activity is bank movement; the system's value is **trustworthy books you
can keep yourself**, with bank reconciliation as the control that earns the
trust.

> Multiple bounded contexts are defined below. There is no code structure yet,
> so the context map lives inline here. When code lands, split this into a
> root `CONTEXT-MAP.md` plus a `CONTEXT.md` per context directory.

## Context map

| Context | Classification | Role |
|---|---|---|
| **Bank Reconciliation** | Core | Control: matches bank statement lines to ledger bank postings; owns clearance state; raises discrepancies for human review |
| **General Ledger** | Supporting (correctness backbone) | System-of-record; mostly event-fed. Owns Chart of Accounts, Journal/Posting, period closing, the guarded guided-journal path |
| **Invoicing/AR** | Supporting | Sell-side capture; upstream source of Accounts Receivable |
| **Expense Management** | Supporting | Buy-side outflow capture (owner-reimbursable + direct-bank rails) |
| **Party** | Generic | Shared master data; customer/supplier/contractor are roles |
| **Reporting** | Generic | Pure derivable read model; no writes |

**Out of v1:** Budgeting/Planning · Payroll-proper (withholding/statutory) ·
full Accounts Payable · period-end FX revaluation · analytical dimensions
beyond Party · bank-feed auto-import (statements are imported, matching is
assisted, not autonomous).

## Language

**General Ledger**:
The single system-of-record for double-entry postings, measured in the
functional currency.
_Avoid_: "the books" (informal), "accounts" (ambiguous — see Account)

**Chart of Accounts**:
The classified tree of postable accounts. An *aggregate inside* General
Ledger, not its own context.
_Avoid_: COA as a separate system

**Account**:
A node in the Chart of Accounts that postings target. Carries a tax-treatment
classification.
_Avoid_: using "account" to mean a bank login, a Customer, or a Party

**Posting / Journal Line**:
One leg of a balanced journal entry: `(Account, amount, Dr/Cr, dimensions)`.
Carries per-line **dimensions** (Party in v1; Project later).
_Avoid_: "entry" for a single line (an entry is the balanced set of lines)

**Dimension**:
A typed analytical tag on a journal line used to slice reports (Party in v1).
_Avoid_: tag, category, cost-centre

**Party**:
A person or organization the business transacts with. Plays **roles**:
customer, supplier, contractor. Referenced elsewhere by `PartyId` only.
_Avoid_: separate "Customer" and "Supplier" entities; client, vendor

**Invoice**:
A request for payment issued to a customer, denominated in its own
transaction currency. Source of an AR balance until paid.
_Avoid_: bill (a bill is something received, not issued)

**Paid** (of an Invoice):
A **human assertion** that the customer's funds have already been confirmed in
the bank. Not provisional, not system-gated.
_Avoid_: treating "paid" as "recorded but unconfirmed"

**Cleared** (of a bank Posting):
Statement-confirmed by Bank Reconciliation. Distinct from an Invoice being
"paid".
_Avoid_: conflating cleared with paid

**Transfer slip**:
Customer-supplied proof of a bank transfer, attached to an invoice payment as
audit evidence.

**Owner-reimbursable expense**:
A business expense the owner pays personally (typically on a personal or
mixed-use credit card). Recognized at the moment of the charge; the
obligation is the business's, owed to the **owner**. Personal charges on the
same card never enter the business books — only the individual business
expenses do.
_Avoid_: "card expense" (the card is personal and off the books), modelling
the personal card statement

**Due to Owner**:
The single accrued payable (ADR-0003): the running liability the business
owes the owner for owner-reimbursable expenses. `Dr Expense / Cr Due to
Owner` at the charge; `Dr Due to Owner / Cr Bank` when the business
reimburses the owner. Its balance is "how much I am owed" at any time.
_Avoid_: Accounts Payable; credit-card clearing account; treating it as
owner equity / an owner draw (reimbursement settles a debt, it is not a draw)

**Contractor payment**:
A categorized direct-bank outflow to a Party in the contractor role. The v1
meaning of "salary". No employment, no withholding.
_Avoid_: payroll, salary (no employees exist)

**Guided-journal path**:
The single narrow, role-restricted route for writing to the Ledger directly:
opening balances, corrections, closing entries, owner draws, capital
injections, statement-only items (e.g. bank fees).
_Avoid_: "manual journal" implying free-hand access

**Functional currency**:
MYR — the measurement currency of the Ledger and all statements.

**Transaction currency**:
The currency an invoice is denominated in (e.g. SGD), with a manually-entered
booking rate at issue.

**Realized FX gain/loss**:
The MYR difference between an invoice's booked AR carrying value and the MYR
actually banked at settlement. Recognized only at settlement.

**Fiscal year**:
Calendar year (Jan–Dec), fixed by the sole-proprietor calendar-year basis of
assessment. Single configurable setting.

**Soft close** (of a month):
The routine lock of a completed month; corrections allowed only via the
guided-journal path with a reason. No closing entries posted.

**Hard close** (annual):
Year-end close that posts closing entries (net P&L → Owner's Equity) via the
guided-journal path, after which the fiscal year is immutable. This is what
the original "closing accounts" requirement means.
_Avoid_: "closing" unqualified — always say soft or hard

**Reconciling item**:
An uncleared bank posting carried across a period boundary, classified as
either a timing difference or a stale exception.

**Timing difference**:
A reconciling item expected to clear shortly (deposit in transit, statement
not yet available). Benign.

**Stale exception**:
A reconciling item uncleared beyond the owner-configurable threshold — the
real control signal (phantom payment, mis-keyed amount, unsettled slip).

## Relationships

- **Invoicing → General Ledger**: event-driven, upstream/downstream. Ledger
  translates `InvoiceIssued` / `PaymentRecorded` into postings.
- **Expense Management → General Ledger**: event-driven; owner-reimbursable
  expense captured, owner reimbursed, contractor paid.
- **Bank Reconciliation → General Ledger**: matches `StatementLine ↔ ledger
  bank Posting`; owns the posting's clearance state; unmatched lines feed the
  guided-journal path.
- **Bank Reconciliation ⇒ Invoicing**: after-the-fact audit. Raises
  discrepancies for human review; does **not** gate "paid".
- **Party** is referenced by `PartyId` (+ cached display name) from Ledger
  dimensions, Invoicing, Expense Management. Not a shared kernel.
- **Reporting** is downstream of everything; read-only projections.
- A foreign-currency **Invoice** that settles for less MYR than expected is
  **ambiguous** (underpayment vs FX) and is **human-adjudicated**, never
  auto-resolved.
- **Soft close** and **clearance** are orthogonal: soft close never blocks on
  uncleared items; clearance-state mutation is exempt from the period lock.
- **Hard close** blocks until every uncleared item is classified as a
  year-end reconciling item or adjudicated via the guided-journal path.

## Asserted invariants (the system computes and displays these, never assumes)

1. Every journal entry: Σ debits = Σ credits.
2. Ledger AR control = Σ (issued, unpaid invoices).
3. Confirmed cash = Σ cleared bank postings.
4. Every statement line ends matched or explicitly explained; reconciled bank
   balance ties to the statement closing balance.

## Example dialogue

> **Dev:** "When I mark invoice #42 **paid**, should Bank Reconciliation
> confirm it before AR clears?"
> **Owner:** "No. I only mark it paid *after* I've seen the money in the bank
> and got the transfer slip. Reconciliation is the systematic check that I
> didn't make a mistake — it audits me afterwards, it doesn't gate me."
> **Dev:** "And if the SGD invoice was 1,000 but only MYR 3,180 landed?"
> **Owner:** "That might be FX, or they underpaid. Don't guess — show me both
> numbers and let me decide *settled in full* or *still owes*."

## Flagged ambiguities (resolved)

- "account" meant both a Chart-of-Accounts node and a bank login / Party —
  resolved: **Account** is a CoA node only; bank logins and parties are
  distinct.
- Chart of Accounts proposed as its own bounded context — resolved: it is an
  **aggregate inside General Ledger** (see ADR-0001).
- "salary" implied employees/payroll — resolved: it means **contractor
  payment**, no employment.
- "supplier" implied Accounts Payable — resolved: **Supplier is master data**;
  cash basis on purchases, the only payable is **Due to Owner** (the
  owner-reimbursement liability — the card is personal, not a business
  creditor; superseded the earlier credit-card-clearing assumption).
- "paid" vs "cleared" conflated — resolved: distinct concepts (see ADR-0004).
