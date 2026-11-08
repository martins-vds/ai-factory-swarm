# Monthly lending report (specification)

The legacy reporting module was a separate product whose code and runtime are lost. This specification is
all that remains. (Scenario `spec-only`, ADR-0037.)

- Run on the first day of each month for the previous month.
- One row per member: member id, loans started, loans returned late, total late fees in cents.
- Sorted by total late fees, highest first; ties by member id.
- Members with no loans in the month are omitted.
