from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Platform = Literal['claude', 'copilot']

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WRITING_SKILLS_CHECKLIST = (
    (_REPO_ROOT / 'criteria' / 'writing-skills-criteria.md')
    .read_text(encoding='utf-8')
    .strip()
)


@dataclass(frozen=True, slots=True)
class Capability:
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
    return [
        f'tool exceeds least authority: {tool}' for tool in tools if tool not in allowed
    ]
