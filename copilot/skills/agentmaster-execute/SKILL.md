---
name: agentmaster-execute
description: Execute an agentmaster plan. Use when the user asks to execute, implement, or run a plan produced by agentmaster-plan, or invokes /agentmaster-execute. Honors the plan's execution mode (sequential default, justified parallel with optional pilot), gates every task on verification, re-verifies independently, runs the coherence pass, then chains into the review.
---

This skill is a router. Execution runs inside the `agentmaster-execute`
custom agent, which dispatches implementer workers and never edits files in
this session.

Invoke the `agentmaster-execute` custom agent now, passing the plan path or
scope and any `--headless` flag verbatim. Do not implement the plan inline.
If the custom agent is not available, tell the user to run
`python install.py install --target copilot` from the agentmaster bundle.

Plan: $ARGUMENTS
