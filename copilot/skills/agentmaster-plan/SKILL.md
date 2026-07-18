---
name: agentmaster-plan
description: Cost-tiered planning pipeline. Use when the user asks to plan a feature, refactor, migration, or fix with agentmaster, or invokes /agentmaster-plan. A frontier orchestrator dispatches cheap scout/code-analyst workers for evidence, detects the project toolchain, drafts a parallel-safe plan with an evidence ledger, and survives adversarial critique. Supports --lite and --headless.
---

This skill is a router. The pipeline runs inside the `agentmaster-plan`
custom agent, which carries the frontier model pin and the agent/todo-only
tool restriction that enforces the cost boundary.

Invoke the `agentmaster-plan` custom agent now, passing the user's task and
any `--lite` or `--headless` flags verbatim. Do not run the pipeline inline
in this session — the cost boundary depends on the coordinator's restricted
toolset. If the custom agent is not available, tell the user to run
`python install.py install --target copilot` from the agentmaster bundle.

Task: $ARGUMENTS
