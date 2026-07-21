## Summary

<!--
    explain what changed and why. keep this focused on the outcome.
-->

## Changes

-

## Verification

- [ ] `python install.py sync`
- [ ] `bash scripts/code-quality.sh all`
- [ ] `git diff --check`
- [ ] Focused tests for the changed behavior pass.
- [ ] Generated Claude and Copilot files remain in sync.

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
