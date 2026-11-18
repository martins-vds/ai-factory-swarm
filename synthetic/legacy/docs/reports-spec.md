# Monthly lending report (specification)

The reporting module was a separate product; its code and runtime are no longer available. This specification is
all that remains.

- Run on the first day of each month for the previous month.
- One row per member: member id, loans started, loans returned late, total late fees in cents.
- Sorted by total late fees, highest first; ties by member id.
- Members with no loans in the month are omitted.
