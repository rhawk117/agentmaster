Evidence axes — dispatch all in parallel, each under the standard report
contract and the scout-to-analyst escalation ladder:

- Correctness, bugs, and regressions — scout: run the FULL suite (the plan's
  toolchain test command), not only changed-file tests, plus coverage for
  changed files. code-analyst: any behavior change the plan did not call for
  is a regression finding, whether or not a test caught it; for each changed
  behavior, would the covering test fail if it were wrong? Name untested
  branches by file:line. A test that passes regardless of the code is a
  finding.
- Structure quality — code-analyst: concrete SOLID, YAGNI, and DRY findings
  only — duplicated logic (both locations), speculative abstraction nothing
  uses, responsibilities crossing boundaries, functions doing several jobs —
  and where the code follows the principles, so adjudication sees both sides.
- Testability — code-analyst: behaviors that cannot be exercised without
  heavy scaffolding, hidden dependencies that block isolation, tests that
  pass regardless of the code under test.
- Flexibility to change — code-analyst: coupling or hardcoding that makes a
  named, plausible next change expensive. Every flexibility finding must
  state the concrete anticipated change it protects; without one it is
  speculative generality and will be rejected.
- Security — scout: run the static analysis the plan's toolchain section
  records, or what the ecosystem provides (bandit or semgrep for Python,
  eslint security rules or npm audit for JS/TS, gosec for Go, cargo audit
  for Rust, SpotBugs for the JVM), on changed paths. code-analyst: review
  the diff hunks for input handling, authn/z changes, secrets, injection
  surfaces, unsafe deserialization, path handling.

Severity calibration: structure, testability, and flexibility findings are
capped at major — design quality earns fixes, never a block by itself; if a
design flaw hides a correctness or security consequence, classify it under
that axis, where blocker is available. Bugs, regressions, and security
findings may take any severity.
