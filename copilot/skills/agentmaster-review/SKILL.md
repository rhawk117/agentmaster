---
name: agentmaster-review
description: Adversarial code review with the agentmaster evidence pipeline. Use when the user asks for an agentmaster review of a diff, branch, or change set, or invokes /agentmaster-review. Assumes the code is guilty until proven working across correctness, structure, testability, flexibility, and security axes, with severity calibration and adjudicated findings.
---

This skill is a router. The review runs inside the `agentmaster-review`
custom agent, which carries the frontier model pin and dispatches scout and
code-analyst workers for all evidence.

Invoke the `agentmaster-review` custom agent now, passing the diff range or
scope verbatim. Do not review inline in this session. If the custom agent is
not available, tell the user to run `install-copilot.sh` from the
agentmaster bundle.

Scope under review: $ARGUMENTS
