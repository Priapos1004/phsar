---
description: Test-authoring invariants — proving a new test is a guard, asserting on the path rather than an environment-dependent output, teardown for anything that outlives its call, and what jsdom cannot assert.
paths: "phsar/{tests,frontend/src/tests}/**/*"
---

# Writing a test

How to **run** the suites is in root `CLAUDE.md`.

## A new test is not a guard until it has been seen to fail

Break the code it covers, confirm the test fails, revert. A green run cannot
tell a real guard from a vacuous one, so the sabotage **is** the verification.

A tiebreak or precedence assertion is only a guard when every *other* mechanism
in the code under test points the opposite way. Otherwise it passes for a reason
unrelated to what it claims: the fixture happens to agree with the fallback, and
the test survives deleting the rule it was written for.

Where a test genuinely cannot separate two implementations, **say so** rather
than leaving it looking like coverage.

## Where the invariant is "this path is never taken", assert on the path

Spy the call that must not happen, rather than the output it would have produced.

`TZ` is the standing case: Node reads it **once at startup**, so a per-test
reassignment changes nothing and the loop that looks like a matrix runs one
zone. `rules/frontend.md` carries the date-formatter instance and its guard.

## Anything that outlives its call needs teardown

Cancel the frame, clear the timer, unsubscribe — from `afterEach`, or through a
disposer the test calls. A `requestAnimationFrame` loop still scheduling past the
end of its test fires into the **next** one, against a detached node and the
shared spy.

**Its symptom is never the test that caused it** — a neighbouring test fails,
usually with an inflated call count. Look at what the previous test started.

## jsdom has no layout, paint or scrolling

So an assertion about *when* something lands is a timer assertion wearing a paint
assertion's clothes. Split the arithmetic into a pure function, keep the DOM half
thin, and state which half is actually covered. Where the real check is a human
looking at the page, `rules/frontend.md` governs the handoff.

## A cross-file invariant needs an importable form

Two files that must agree, with a comment on each saying they do, are checked by
nothing. Export the shared fact from one owner, have the other derive from it,
and walk it in a test.

A constant in a component's **instance** `<script>` is unreachable from a test —
only a `<script module>` block can export — so a fact a component must share
belongs in the util that owns it, not in the component.
