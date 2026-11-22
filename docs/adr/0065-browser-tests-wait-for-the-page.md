# ADR-0065: Browser tests wait for the page

- Status: Proposed (merging the harness PR that adds it accepts it; it blocks where the profile sets
  `test_health.block`, as ADR-0064 does)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), step 4.5; eval step 2.4 (runs `sf-r1`, PRs #2297 and
  #2299 in the eval repo); LL-01 and LL-03 browser failures of 2026-11-21

## Context
Browser tests failed more Migrator runs than any other cause in the step 2.4 eval: two of the three LL-03
failures. Both were test bugs that read like product failures.

- **#2297:** the test clicked "Pay late fee", then `assert page.get_by_role('alert').inner_text() == …`.
  `inner_text()` waits for the element only, not for the text, and a plain `assert` never retries. LL-01's
  earlier failure was the same pattern with `is_visible()`, which returns at once.
- **#2299:** `assert request.headers.get('HX-Request') == 'true'` got `None` every time, because Playwright
  lowercases header names.

Both patterns are visible in the code. Playwright's `expect(...)` assertions retry until they hold, and
`header_value()` or the lowercase name always matches.

## Decision
1. **The coupling guard (`afs-test-health --check`, ADR-0064) also checks browser tests**, in files that use
   Playwright, on the lines a branch adds:
   - an `assert` on a read that returns at once (`is_visible`, `is_hidden`, `is_enabled`, `is_checked`,
     `inner_text`, `text_content`, `input_value`, `get_attribute`, `count`, and the like) is a
     **non-waiting browser assertion**. The hint is `expect(locator).to_be_visible()` / `.to_have_text(…)`;
   - `headers.get("Name")` or `headers["Name"]` with capitals is a **header lookup with capitals**. The hint
     is the lowercase name, or `header_value()`.
2. **`# afs: allow-browser <why>` exempts a line**, with a reason, like `allow-mock`. An example is a `count()`
   on markup the server renders and nothing changes afterwards.
3. **The same switch as ADR-0064:** these findings report, or block with `test_health.block`. The skills say it
   where the tests are written: `afs-specialty` for UI tickets, and `references/gates.md`.

## Consequences
- The two step 2.4 failures would have been sent back with the exact fix before the PR was opened.
- It's a syntax check. A test can still wait for the wrong thing, for example a `wait_for()` on an element that
  shows before the update. A flake that remains is phase 5's quarantine (step 5.2).
- Rejected: forcing `expect` everywhere with a Playwright plugin. Tests written before the rule would fail,
  and the guard checks only new lines.
