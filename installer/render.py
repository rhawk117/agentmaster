from pathlib import Path
from typing import TYPE_CHECKING, Literal

from installer.frontmatter import update_frontmatter
from installer.manifest import MANIFEST, Manifest

if TYPE_CHECKING:
    from collections.abc import Mapping

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
    overrides: Mapping[str, str] | None = None,
) -> str:
    frontmatter = (
        manifest.claude_frontmatter
        if platform == 'claude'
        else manifest.copilot_frontmatter
    )[name]
    body = _body(name, platform, manifest, root or _DEFAULT_ROOT)
    rendered = f'---\n{frontmatter}---\n\n{_marker(name)}\n\n{body}\n'
    if overrides:
        rendered = update_frontmatter(rendered, overrides)
    return rendered


def generated_path(name: str, platform: Platform, root: Path) -> Path:
    if platform == 'claude':
        return root / 'agents' / f'{name}.md'
    return root / 'copilot' / 'agents' / f'{name}.agent.md'


def sync_workers(root: Path, manifest: Manifest = MANIFEST) -> list[Path]:
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
