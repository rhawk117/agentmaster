"""Frozen manifest of worker frontmatter and per-platform substitutions.

Every consumer takes a :class:`Manifest` by injection so tests can pass fakes.
Frontmatter blocks are copied byte-for-byte from the committed agent files.
"""

# ruff: noqa: E501 -- frontmatter descriptions are verbatim copy and exceed the line limit

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class Manifest:
    """Static description of the worker agents and their platform variants."""

    workers: tuple[str, ...]
    claude_skills: tuple[str, ...]
    copilot_coordinators: tuple[str, ...]
    claude_only_agents: tuple[str, ...]
    claude_hooks: tuple[str, ...]
    copilot_hooks: tuple[str, ...]
    claude_frontmatter: Mapping[str, str]
    copilot_frontmatter: Mapping[str, str]
    substitutions: Mapping[str, Mapping[str, str]]


_CLAUDE_FRONTMATTER: Mapping[str, str] = {
    'scout': """\
name: scout
description: Cheap mechanical retrieval — locate files and symbols, list dependencies and versions, run a single command or test and capture output, extract specific facts from specific files. Use for questions with a definite answer that require no interpretation.
tools: Read, Grep, Glob, Bash
model: haiku
effort: low
maxTurns: 15
color: cyan
""",
    'code-analyst': """\
name: code-analyst
description: Mid-cost interpretation — trace how code works across files, reproduce and analyze test failures, research dependency changelogs and upgrade impact, run code-graph and architecture queries. Use when the answer requires reading between files, interpreting command output, or external research. Also the escalation target when scout is blocked.
tools: Read, Grep, Glob, Bash, WebSearch, WebFetch  # append your code-graph MCP server here, e.g. mcp__graphify, to allow graph queries
model: sonnet
effort: medium
maxTurns: 30
color: blue
""",
    'plan-critic': """\
name: plan-critic
description: Fresh-context adversarial review of a draft implementation plan. Dispatched by agentmaster-plan with the goal, constraints, draft skeleton, and evidence ledger. Assumes the plan is wrong and hunts for the flaw, verifying claims against the repository read-only.
tools: Read, Grep, Glob, Bash
model: sonnet
effort: high
maxTurns: 20
color: red
""",
    'implementer': """\
name: implementer
description: Executes exactly one task group from an approved implementation plan — edits only the files the group owns, runs each task's verification, reports results. Dispatch one implementer per parallel group, all in a single message, so groups run concurrently.
tools: Read, Edit, Write, Grep, Glob, Bash, Skill
model: sonnet
effort: medium
maxTurns: 50
color: green
# isolation: worktree  # uncomment to give each implementer an isolated git worktree instead of relying on disjoint file ownership
""",
    'git-publisher': """\
name: git-publisher
description: Coordinator-owned bounded git/GitHub operations — stage, commit, push, open/reconcile a PR, watch CI, and merge only on an exact PR/CI/review head match. Never edits repository files and never force-pushes. Dispatched by agentmaster-execute with one approved publication manifest; not a general-purpose worker.
tools: Read, Bash
model: sonnet
effort: medium
maxTurns: 20
color: yellow
""",
}

_COPILOT_FRONTMATTER: Mapping[str, str] = {
    'scout': """\
name: scout
description: Cheap mechanical retrieval — locate files and symbols, list dependencies and versions, run a single command or test and capture output, extract specific facts. Delegation-only worker for the agentmaster-plan and agentmaster-review coordinators.
user-invocable: false
tools: ['read', 'search', 'execute']
model: claude-haiku-4.5
""",
    'code-analyst': """\
name: code-analyst
description: Mid-cost interpretation — trace how code works across files, reproduce and analyze test failures, research dependency changelogs, run code-graph queries. Escalation target when scout is blocked. Delegation-only worker.
user-invocable: false
tools: ['read', 'search', 'execute', 'web']
model: claude-sonnet-4.6
""",
    'plan-critic': """\
name: plan-critic
description: Fresh-context adversarial review of a draft implementation plan. Assumes the plan is wrong and hunts for the flaw, verifying claims against the repository read-only. Delegation-only worker for agentmaster-plan.
user-invocable: false
tools: ['read', 'search', 'execute']
model: claude-sonnet-4.6
""",
    'implementer': """\
name: implementer
description: Executes exactly one task group from an approved plan — edits only the files the group owns, runs each task's verification, reports. Delegation-only worker; one implementer per parallel group.
user-invocable: false
tools: ['read', 'search', 'execute', 'edit']
model: claude-sonnet-4.6
""",
    'git-publisher': """\
name: git-publisher
description: Coordinator-owned bounded git/GitHub operations — stage, commit, push, open/reconcile a PR, watch CI, merge only on an exact PR/CI/review head match. Never edits repository files, never force-pushes. Delegation-only worker for agentmaster-execute.
user-invocable: false
tools: ['read', 'execute']
model: claude-sonnet-4.6
""",
}

_USES_RULE_CLAUDE = """\
If your task carries a `Uses:` line, invoke that capability through the
   Skill tool for that task rather than improvising the workflow it encodes —
   the planner chose it deliberately."""

_USES_RULE_COPILOT = """\
If the task names a repository skill, instructions file, or tool under a
   `Uses:` line, read and follow it rather than improvising the workflow it
   encodes."""

MANIFEST = Manifest(
    workers=('scout', 'code-analyst', 'plan-critic', 'implementer', 'git-publisher'),
    claude_skills=(
        'agentmaster-plan',
        'agentmaster-execute',
        'agentmaster-review',
        'agentmaster-retro',
    ),
    copilot_coordinators=(
        'agentmaster-plan',
        'agentmaster-execute',
        'agentmaster-review',
        'agentmaster-retro',
    ),
    claude_only_agents=('explore',),
    claude_hooks=(
        'cost_boundary.py',
        'dispatch_guard.py',
        'execute_stop.py',
        'hooklib.py',
        'precompact_snapshot.py',
        'session_context.py',
        'subagent_start.py',
        'telemetry.py',
    ),
    copilot_hooks=(
        'copilot_telemetry_post.py',
        'copilot_telemetry_pre.py',
        'hooklib.py',
        'session_context.py',
    ),
    claude_frontmatter=_CLAUDE_FRONTMATTER,
    copilot_frontmatter=_COPILOT_FRONTMATTER,
    substitutions={
        '%USES_RULE%': {'claude': _USES_RULE_CLAUDE, 'copilot': _USES_RULE_COPILOT},
    },
)
