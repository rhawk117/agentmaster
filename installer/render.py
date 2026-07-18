"""Render worker agent files from the canonical shared bodies + manifest.

The canonical body of each worker lives in `shared/agents/<name>.md` (no
frontmatter, no marker). Platform-specific frontmatter and the `%USES_RULE%`
substitution come from an injected :class:`Manifest`, so the same body renders
both the Claude (`agents/<name>.md`) and Copilot (`copilot/agents/<name>.agent.md`)
variants.
"""

from pathlib import Path
from typing import Literal

from installer.manifest import MANIFEST, Manifest

Platform = Literal['claude', 'copilot']

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent


def _marker(name: str) -> str:
    return (
        f'<!-- generated from shared/agents/{name}.md '
        '— edit there and run: python install.py sync -->'
    )


def _body(name: str, platform: Platform, manifest: Manifest, root: Path) -> str:
    source = root / 'shared' / 'agents' / f'{name}.md'
    text = source.read_text(encoding='utf-8').rstrip('\n')
    for token, replacements in manifest.substitutions.items():
        text = text.replace(token, replacements[platform])
    return text


def render_worker(
    name: str,
    platform: Platform,
    manifest: Manifest = MANIFEST,
    root: Path | None = None,
) -> str:
    """Return the full generated file content for one worker on one platform.

    Bodies come from `root/shared/agents/`; `root` defaults to the repository
    that contains this module.
    """
    frontmatter = (
        manifest.claude_frontmatter
        if platform == 'claude'
        else manifest.copilot_frontmatter
    )[name]
    body = _body(name, platform, manifest, root or _DEFAULT_ROOT)
    return f'---\n{frontmatter}---\n\n{_marker(name)}\n\n{body}\n'


def generated_path(name: str, platform: Platform, root: Path) -> Path:
    """Return the committed output path for a worker under `root`."""
    if platform == 'claude':
        return root / 'agents' / f'{name}.md'
    return root / 'copilot' / 'agents' / f'{name}.agent.md'


def sync_workers(root: Path, manifest: Manifest = MANIFEST) -> list[Path]:
    """Regenerate every worker file under `root`; return the written paths."""
    written: list[Path] = []
    for name in manifest.workers:
        for platform in ('claude', 'copilot'):
            path = generated_path(name, platform, root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                render_worker(name, platform, manifest, root), encoding='utf-8'
            )
            written.append(path)
    return written
