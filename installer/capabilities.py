"""Registry of agentmaster's own first-class plan capabilities.

A plan's `Uses:` line may name any skill, agent, or tool the planner found in
its Phase 1 inventory — that stays free text. This module registers only the
small set of capabilities agentmaster itself defines special handling for
(currently `writing-skills`, Section 20.1): each carries the checklist the
orchestrator embeds in context, the tools it may hold at least authority, and
the frontmatter keys a target platform requires.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Platform = Literal['claude', 'copilot']

# The writing-skills checklist is canonically criteria/writing-skills-criteria.md
# (injected verbatim into agentmaster-execute's SKILL.md/agent.md and drift-checked
# by installer.parity) — loaded here so callers get the same text in memory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_WRITING_SKILLS_CHECKLIST = (
    (_REPO_ROOT / 'criteria' / 'writing-skills-criteria.md')
    .read_text(encoding='utf-8')
    .strip()
)


@dataclass(frozen=True, slots=True)
class Capability:
    """A structured plan capability with its trigger scope and checklist."""

    name: str
    trigger_keywords: tuple[str, ...]
    allowed_tools: frozenset[str]
    checklist: str


CAPABILITIES: dict[str, Capability] = {
    'writing-skills': Capability(
        name='writing-skills',
        trigger_keywords=(
            'skill.md',
            '.agent.md',
            'shared/agents/',
            'installer/manifest.py',
            'frontmatter',
        ),
        allowed_tools=frozenset({'Read', 'Grep', 'Glob', 'Edit', 'Write'}),
        checklist=_WRITING_SKILLS_CHECKLIST,
    ),
}

_REQUIRED_FRONTMATTER_KEYS: dict[Platform, tuple[str, ...]] = {
    'claude': ('name', 'description', 'model'),
    'copilot': ('name', 'description', 'model'),
}


def validate_frontmatter(frontmatter_text: str, *, platform: Platform) -> list[str]:
    """Return one error per required frontmatter key missing for `platform`.

    Parameters
    ----------
    frontmatter_text : str
        The raw YAML frontmatter block (without the `---` fences).
    platform : Platform
        The target schema to validate against.

    Returns
    -------
    list[str]
        Empty when every required key for `platform` is present.
    """
    present = {
        line.split(':', 1)[0].strip()
        for line in frontmatter_text.splitlines()
        if ':' in line
    }
    return [
        f'missing required frontmatter key for {platform}: {key}'
        for key in _REQUIRED_FRONTMATTER_KEYS[platform]
        if key not in present
    ]


def check_tool_authority(tools: tuple[str, ...], allowed: frozenset[str]) -> list[str]:
    """Return one error per tool in `tools` that exceeds `allowed` — least authority.

    Parameters
    ----------
    tools : tuple[str, ...]
        The tools a target frontmatter block grants.
    allowed : frozenset[str]
        The capability's least-authority allowlist.

    Returns
    -------
    list[str]
        Empty when every tool in `tools` is within `allowed`.
    """
    return [
        f'tool exceeds least authority: {tool}' for tool in tools if tool not in allowed
    ]
