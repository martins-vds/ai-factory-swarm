---
name: afs-implement
description: "Implement a piece of work based on a spec or set of tickets."
---

> Vendored by AI Factory Swarm from [mattpocock/skills](https://github.com/mattpocock/skills/tree/a496f5513d4a4cf889bc48e189e579f4b0bdf6aa/skills/engineering/implement) at `a496f55` (see PROVENANCE.md). Changes: renamed to `afs-implement`; model invocation enabled so unattended role agents can run it.

Implement the work described by the user in the spec or tickets.

If the user passes a ticket reference, fetch it from the issue tracker and state its title before starting. If the reference is ambiguous, ask.

Call the Skill tool with "tdd" where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, call the Skill tool with "code-review" to review the work.

Commit your work to the current branch.
