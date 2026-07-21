## Summary

<!--
    explain what changed and why. keep this focused on the outcome.
-->

## Scope

<!-- what this PR touches, in one or two sentences. -->

### Non-goals

<!-- what this PR deliberately does not do, so reviewers don't ask for it. -->
-

## Changes

-

## Schema / settings migration

<!-- ledger schema, config precedence, or generated-file shape changes.
     write "None." if there are none. -->

## Rollback

<!-- how to revert this if it ships broken (revert commit, delete a tag, etc). -->

## Criteria / evidence

<!-- file:line evidence supporting the change, and/or the criteria this
     satisfies (e.g. a SPEC.md microtask's focused verification). -->

## Token / cost effect

<!-- new dispatches, model pins, or maxTurns/effort changes and their cost
     impact. write "None." if there are none. -->

## Verification

- [ ] `python install.py sync`
- [ ] `bash scripts/code-quality.sh all`
- [ ] `git diff --check`
- [ ] Focused tests for the changed behavior pass.
- [ ] Generated Claude and Copilot files remain in sync.

### Manual checks

<!-- anything verified by hand rather than by an automated command. -->
-

## Final checklist

- [ ] No secrets, credentials, private paths, or user data are included.
- [ ] New filesystem, command, hook, ledger, or external-write behavior has been
      reviewed for trust-boundary impact.
- [ ] Logs, telemetry, artifacts, and errors follow the repository's redaction
      and retention rules.
- [ ] This PR does not weaken current-head CI, review, ownership, or rollback
      guarantees.
- [ ] The branch started from the latest `develop`.
- [ ] The change is limited to one coherent task.
- [ ] Commits follow the repository's conventional commit style.
- [ ] Every logical commit was pushed after creation.
- [ ] Tests assert observable behavior rather than implementation details.
- [ ] Comments explain only invariants, hazards, compatibility facts, or
      non-obvious decisions.
- [ ] Runtime code remains compatible with the documented Python 3.14 contract.
- [ ] No new runtime dependency was added unless explicitly approved.
- [ ] CI is green for the current PR head.
- [ ] Independent review is `GOOD` for that same head SHA.

Reviewed SHA: `<paste the exact commit SHA the reviewer approved>`

Verdict: `GOOD` / `NEEDS-WORK`
