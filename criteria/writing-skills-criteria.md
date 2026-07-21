Writing-skills checklist — before treating a task's SKILL.md, agent
definition, frontmatter, invocation example, or skill test as done, confirm
every item below and note file:line evidence for any that fail:

- Trigger and non-trigger boundaries — the description names what earns
  invocation and what does not; a skill that fires on everything is a
  routing defect.
- Least authority — the tools list holds only what the skill's job needs;
  no blanket Bash/Write grant "just in case".
- Target-specific frontmatter validity — required keys and value shapes
  match the target platform's schema (Claude vs Copilot), not just the
  source platform's.
- Explicit handoff and output schema — the skill states what it hands back
  and in what shape, so the caller can consume it without guessing.
- Idempotent, recoverable behavior — re-running the skill after a partial
  or interrupted run does not duplicate work or corrupt state.
- Stop conditions and failure semantics — the skill states when it halts
  and what a caller sees on failure, not just on success.
- Examples and tests exercise invocation, not prose quality — at least one
  test drives the skill through its trigger and non-trigger paths.
- Generated parity and documentation — canonical source and every rendered
  or copied target agree, and docs referencing the skill are updated in
  the same change.

This is task-scoped expertise for the task that carries `Uses: writing-skills`
— it is not permission to install or modify unrelated skills. Changes to the
writing-skills capability itself require independent review and
procedure-version evaluation.
