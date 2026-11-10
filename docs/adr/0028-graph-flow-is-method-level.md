# ADR-0028: Graph flow is method-level

- Status: Accepted (martins-vds, 2026-11-03: option 1 on #47)
- Issue: #47

## Context
The pilot's Analyst (HR-02, pilot #115) found the data path for `POST /handling/reports` going through
`JmsApplicationEvents →publishes→ CargoHandledQueue`. The REST method actually sends to the
**registration-attempt** queue; only after registration does a different method send to
`CargoHandledQueue`.

The graph was class-level. `JmsApplicationEvents` declares five queues, so the class "published" to all
five, and the breadth-first search took whichever was shortest. The path was real code but not the real
flow, and a gate can pass on such a path. The same imprecision applied to every multi-purpose class:
CDI event producers, repositories that read in one method and write in another, and services.

## Decision
1. **Methods are nodes.**
   - The Graphify merge keeps each method as a `method` node `Type.name`, which its type `contains`.
   - Calls keep their method endpoints.
   - An implementing type's method `implements` the interface method of the same name, so dispatch is
     followed method by method.
2. **Framework rules attach to the method that does the work.** Each method's text span runs from its
   first line, as Graphify reports it, to the next method's. A rule then attaches to the method whose
   span matches:
   - JPA reads and writes; JMS sends (a method publishes to the queue fields it uses); CDI `fire`;
     `JobOperator.start`;
   - and on the other end: the JAX-RS verb method, the `@MessageDriven` `onMessage`, the `@Observes`
     method, the `@Schedule` method.
   - Django: ORM, render and task enqueues inside a class's method attach to that method.
   - Where the graph knows no methods for a type, the rule falls back to the type, as before.
3. **Entering at a type still reaches all of it.** `contains` is followed, so a page using a bean, a
   batch job calling a bean, an injected dependency, or a constructor call reaches every method of that
   type. That's the honest precision there: a page can call any bean member, and the graph doesn't know
   which method follows a constructor.

## Consequences
- **On the pilot source,** `POST /handling/reports` now follows the real flow:
  `submitReport → receivedHandlingEventRegistrationAttempt → HandlingEventRegistrationAttemptQueue → onMessage → registerHandlingEvent → store → HandlingEvent`.
  Each `JmsApplicationEvents` method publishes only its own queue. Track Cargo's anchors still pass,
  18 of 27 entry points still reach data, and `WS /tracking` still has no path.
- Paths name methods (`Type.method`), which makes them longer but says exactly what runs.
- **Remaining imprecision is visible in the path:** it is a `contains` step after a type-level entry. A
  later refinement could resolve constructor-then-call chains.

## Amendment (2026-11-09, found by the synthetic target's LC-ACCEPT)
LL-02 moved its use cases behind ports: views call `loan_application.lend(...)` on an instance built in a
composition module, and the use case calls a `LoanRepository` Protocol that `DjangoLoanRepository` satisfies
without inheriting it. Every API route lost its path to data. Two rules close the gap:
- **Module-level instances.** The Django enricher resolves `name = SomeClass(...)` at a module's top level, so
  a call `name.method(...)` in a module that imports `name` calls `SomeClass.method` (the class when the graph
  has no method node).
- **Method dispatch for every type-level `implements`.** Each same-named method of the implementing type
  `implements` the interface's method, whoever added the type-level edge. The Graphify merge already did this
  for its own links; a structural match from the base graph didn't get it.

## Amendment (2026-11-10, found by the synthetic target's LF-ACCEPT)
The circulation run passed because the base graph's AI-assisted step happened to emit the `DjangoLoanRepository`
implements `LoanRepository` edge and the calls through `self.repository`. The fees run's base graph had neither,
and 10 routes lost their path to data with no code change. The graph's paths must not depend on that step, so
the Python enricher now derives both from the code:
- **Structural Protocols.** A project class that defines every method of a `typing.Protocol` class implements it.
- **Injected dependencies.** In a class whose `__init__` stores an annotated parameter on `self`
  (`self.repository = repository`, `repository: LoanRepository`), a call `self.repository.all()` calls
  `LoanRepository.all` and, for a Protocol, each structural implementation's `all` directly.
