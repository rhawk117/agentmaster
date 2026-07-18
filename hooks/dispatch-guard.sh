#!/usr/bin/env bash
# PreToolUse (Agent) -> block dispatch while CLAUDE_CODE_SUBAGENT_MODEL overrides the tiering
cat > /dev/null
if [ -n "${CLAUDE_CODE_SUBAGENT_MODEL:-}" ]; then
  echo "agentmaster: CLAUDE_CODE_SUBAGENT_MODEL='${CLAUDE_CODE_SUBAGENT_MODEL}' is exported and silently overrides every worker's model pin, defeating the haiku/sonnet tiering. Ask the user to unset it, then retry the dispatch." >&2
  exit 2
fi
exit 0
