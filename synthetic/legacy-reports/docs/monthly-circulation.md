# Monthly circulation report

Produced on the first working day of each month for the previous calendar month, one page per branch.

## Figures

| Figure | How it is counted |
|---|---|
| Loans issued | Loans whose `loaned_on` falls in the month. Renewals are not new loans. |
| Returns | Loans whose `returned_on` falls in the month, whenever they were issued. |
| Still out | Loans issued on or before the last day of the month and not returned by then. |
| Overdue | Of those still out, the ones whose `due_on` is before the last day of the month. |
| Late fees billed | Sum of late fees on loans returned in the month, at the fee schedule in force on the return date. |
| Active members | Members with at least one loan issued in the month. |

## Rules

- A loan issued and returned on the same day counts as both issued and returned.
- Lost items (marked lost by staff) leave "Still out" in the month they are marked and are listed separately.
- Amounts are shown with two decimals and a dollar sign; counts have no thousands separator.
- The report is sorted by branch name; the totals row comes last and is labelled `ALL BRANCHES`.
- A branch with no activity still gets a page, with every figure shown as 0.
