"""Parity tests for single-sourced worker agent definitions."""

import re
from pathlib import Path

from installer.manifest import MANIFEST, Manifest
from installer.render import generated_path, render_worker, sync_workers

REPO_ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = ('claude', 'copilot')


def test_rendered_matches_committed_files():
    for name in MANIFEST.workers:
        for platform in PLATFORMS:
            path = generated_path(name, platform, REPO_ROOT)
            committed = path.read_text(encoding='utf-8')
            assert committed == render_worker(name, platform), (name, platform)


def test_render_output_ends_with_single_newline():
    for name in MANIFEST.workers:
        for platform in PLATFORMS:
            rendered = render_worker(name, platform)
            assert rendered.endswith('\n')
            assert not rendered.endswith('\n\n')


def test_marker_is_first_body_line():
    for name in MANIFEST.workers:
        marker = (
            f'<!-- generated from shared/agents/{name}.md '
            '— edit there and run: python install.py sync -->'
        )
        for platform in PLATFORMS:
            body = render_worker(name, platform).split('---\n', 2)[2]
            assert body.startswith('\n' + marker + '\n\n'), (name, platform)


def test_no_substitution_token_survives():
    for name in MANIFEST.workers:
        for platform in PLATFORMS:
            rendered = render_worker(name, platform)
            assert re.search(r'%[A-Z_]+%', rendered) is None, (name, platform)
            for token in MANIFEST.substitutions:
                assert token not in rendered


def test_claude_frontmatter_stable_facts():
    scout_fm = MANIFEST.claude_frontmatter['scout']
    assert 'model: haiku' in scout_fm
    assert 'maxTurns: 15' in scout_fm
    rendered = render_worker('scout', 'claude')
    assert rendered.startswith(f'---\n{scout_fm}---\n')


def test_implementer_hook_uses_python_guard():
    fm = MANIFEST.claude_frontmatter['implementer']
    assert 'python3 "$HOME/.claude/agentmaster/hooks/git_guard.py"' in fm
    assert 'git-guard.sh' not in fm


def test_scout_and_analyst_carry_plan_mode_caveat():
    phrase = (
        'if workspace writes are blocked, as in plan mode, '
        'return the evidence inline and note that'
    )
    for name in ('scout', 'code-analyst'):
        for platform in PLATFORMS:
            normalized = ' '.join(render_worker(name, platform).split())
            assert phrase in normalized, (name, platform)


def test_sync_workers_idempotent(tmp_path):
    first = sync_workers(tmp_path)
    contents_first = {p: p.read_text(encoding='utf-8') for p in first}
    second = sync_workers(tmp_path)
    contents_second = {p: p.read_text(encoding='utf-8') for p in second}
    assert first == second
    assert contents_first == contents_second


def test_injected_manifest_overrides_default(tmp_path):
    fake = Manifest(
        workers=('scout', 'implementer'),
        claude_skills=(),
        copilot_coordinators=(),
        claude_only_agents=(),
        claude_hooks=(),
        copilot_hooks=(),
        claude_frontmatter={
            'scout': 'name: scout\nmodel: fake-model\n',
            'implementer': 'name: implementer\nmodel: fake-model\n',
        },
        copilot_frontmatter={
            'scout': 'name: scout\n',
            'implementer': 'name: implementer\n',
        },
        substitutions={'%USES_RULE%': {'claude': 'FAKE RULE.', 'copilot': 'FAKE RULE.'}},
    )
    rendered = render_worker('scout', 'claude', manifest=fake)
    assert 'model: fake-model' in rendered
    assert 'model: haiku' not in rendered

    written = sync_workers(tmp_path, manifest=fake)
    assert len(written) == 4
    implementer_out = (tmp_path / 'agents' / 'implementer.md').read_text(encoding='utf-8')
    assert 'FAKE RULE.' in implementer_out
    assert 'MANIFEST' not in implementer_out


def test_manifest_hook_files_exist():
    for name in (*MANIFEST.claude_hooks, *MANIFEST.copilot_hooks):
        assert (REPO_ROOT / 'hooks' / name).is_file(), name
