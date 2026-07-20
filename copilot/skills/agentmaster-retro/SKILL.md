---
name: agentmaster-retro
description: Transcript-driven analyze-fix-verify loop for the agentmaster skill suite. Use when the user wants agentmaster's own skills improved from real usage artifacts (.transcripts/ snapshots, root-level run transcripts, generated docs, telemetry), or invokes /agentmaster-retro.
---

This skill is a router. The retro runs inside the `agentmaster-retro` custom
agent, which dispatches scout, code-analyst, and implementer workers for all
corpus inventory, grading, and fixes.

Invoke the `agentmaster-retro` custom agent now, passing any `--headless`
flag verbatim. Do not run the retro inline in this session. If the custom
agent is not available, tell the user to run
`python install.py install --target copilot` from the agentmaster bundle.

Arguments: $ARGUMENTS
