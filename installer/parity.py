"""Parity validation between the canonical sources and both platforms.

`validate` re-derives everything that is generated or synced and reports any
undeclared difference: missing canonical sources (completeness), committed
worker files that differ from their rendered form (drift), review-criteria
blocks out of sync with `criteria/review-criteria.md`, and stray worker files
no manifest entry declares. Coordinator prose outside the criteria markers is
a declared platform difference and is not compared.
"""

from pathlib import Path

from installer.manifest import MANIFEST, Manifest
from installer.render import generated_path, render_worker

CRITERIA_START = '<!-- agentmaster:criteria:start -->'
CRITERIA_END = '<!-- agentmaster:criteria:end -->'


def _sources(root: Path, manifest: Manifest) -> list[Path]:
    paths = [root / 'shared' / 'agents' / f'{w}.md' for w in manifest.workers]
    paths += [root / 'skills' / s / 'SKILL.md' for s in manifest.claude_skills]
    paths += [root / 'agents' / f'{a}.md' for a in manifest.claude_only_agents]
    paths += [
        root / 'copilot' / 'agents' / f'{c}.agent.md'
        for c in manifest.copilot_coordinators
    ]
    paths += [
        root / 'copilot' / 'skills' / c / 'SKILL.md'
        for c in manifest.copilot_coordinators
    ]
    hooks = set(manifest.claude_hooks) | set(manifest.copilot_hooks)
    paths += [root / 'hooks' / h for h in sorted(hooks)]
    return paths


def _completeness(root: Path, manifest: Manifest) -> list[str]:
    return [
        f'missing source: {path.relative_to(root).as_posix()}'
        for path in _sources(root, manifest)
        if not path.is_file()
    ]


def _drift(root: Path, manifest: Manifest) -> list[str]:
    findings: list[str] = []
    for name in manifest.workers:
        source = root / 'shared' / 'agents' / f'{name}.md'
        if not source.is_file():
            continue  # already reported by completeness
        for platform in ('claude', 'copilot'):
            path = generated_path(name, platform, root)
            rendered = render_worker(name, platform, manifest, root)
            if not path.is_file():
                rel = path.relative_to(root).as_posix()
                findings.append(f'missing generated file: {rel}')
            elif path.read_text(encoding='utf-8') != rendered:
                findings.append(
                    f'drift: {path.relative_to(root).as_posix()} differs from '
                    f'shared/agents/{name}.md — run: python install.py sync'
                )
    return findings


def _review_criteria_targets(root: Path, manifest: Manifest) -> list[Path]:
    targets = []
    if 'agentmaster-review' in manifest.claude_skills:
        targets.append(root / 'skills' / 'agentmaster-review' / 'SKILL.md')
    targets.extend(
        root / 'copilot' / 'agents' / f'{name}.agent.md'
        for name in ('agentmaster-review', 'agentmaster-execute')
        if name in manifest.copilot_coordinators
    )
    return targets


def _retro_criteria_targets(root: Path, manifest: Manifest) -> list[Path]:
    targets = []
    if 'agentmaster-retro' in manifest.claude_skills:
        targets.append(root / 'skills' / 'agentmaster-retro' / 'SKILL.md')
    if 'agentmaster-retro' in manifest.copilot_coordinators:
        targets.append(root / 'copilot' / 'agents' / 'agentmaster-retro.agent.md')
    return targets


# Each canon file is injected verbatim between the criteria markers in every
# target its targets-function names. Adding a rubric means adding one
# (canon path, targets function) pair here — the comparison logic below is
# unchanged per pair.
_CRITERIA_CANONS = (
    (Path('criteria') / 'review-criteria.md', _review_criteria_targets),
    (Path('criteria') / 'retro-criteria.md', _retro_criteria_targets),
)


def _criteria(root: Path, manifest: Manifest) -> list[str]:
    findings = []
    for canon_rel, targets_fn in _CRITERIA_CANONS:
        targets = [t for t in targets_fn(root, manifest) if t.is_file()]
        if not targets:
            continue
        canon_path = root / canon_rel
        if not canon_path.is_file():
            findings.append(f'missing source: {canon_rel.as_posix()}')
            continue
        canon = canon_path.read_text(encoding='utf-8').strip()
        for target in targets:
            text = target.read_text(encoding='utf-8')
            start, end = text.find(CRITERIA_START), text.find(CRITERIA_END)
            rel = target.relative_to(root).as_posix()
            if start < 0 or end < 0:
                findings.append(f'criteria markers missing in {rel}')
            elif text[start + len(CRITERIA_START) : end].strip() != canon:
                findings.append(
                    f'criteria drift: {rel} differs from {canon_rel.as_posix()}'
                )
    return findings


def _strays(root: Path, manifest: Manifest) -> list[str]:
    declared_claude = set(manifest.workers) | set(manifest.claude_only_agents)
    declared_copilot = set(manifest.workers) | set(manifest.copilot_coordinators)
    findings = []
    claude_dir = root / 'agents'
    if claude_dir.is_dir():
        findings += [
            f'undeclared agent file: agents/{p.name}'
            for p in sorted(claude_dir.glob('*.md'))
            if p.stem not in declared_claude
        ]
    copilot_dir = root / 'copilot' / 'agents'
    if copilot_dir.is_dir():
        findings += [
            f'undeclared agent file: copilot/agents/{p.name}'
            for p in sorted(copilot_dir.glob('*.agent.md'))
            if p.name.removesuffix('.agent.md') not in declared_copilot
        ]
    return findings


def validate(root: Path, manifest: Manifest = MANIFEST) -> list[str]:
    """Return all parity findings for the tree at `root` (empty list = pass)."""
    return (
        _completeness(root, manifest)
        + _drift(root, manifest)
        + _criteria(root, manifest)
        + _strays(root, manifest)
    )
