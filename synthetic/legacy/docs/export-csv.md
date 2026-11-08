# CSV export of loans

`GET /loans` returns one line per loan, fields separated by `;` (id, member, isbn, lent on, due on, returned
on). Spreadsheet users rely on it. (Scenario `deferred-capability`, ADR-0037: the operator decides whether it
moves now or later.)
