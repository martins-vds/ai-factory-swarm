# ADR-0007: Quirks and bugs escalate immediately to a human

- Status: Accepted
- Date: 2026-10-30

## Context
A high-fidelity migration will uncover source behavior that looks wrong: defects, odd edge cases,
undefined behavior. Silently preserving them carries bugs forward; silently fixing them breaks the
fidelity contract.

## Decision
When any agent discovers a quirk, it raises a **question ticket** on the decision map **at the moment
of discovery**, with evidence, impact and options (template in architecture §11). The ticket is
assigned to a human and blocks only the tickets that depend on the answer. Any human may answer; the
recipient decides whether to consult a domain expert. Agents never answer their own question.

## Consequences
- Execution continues on unaffected work while the question is open.
- Each resolution is recorded on the ticket and in the affected ledger entries, with a test pinning
  the chosen behavior.
