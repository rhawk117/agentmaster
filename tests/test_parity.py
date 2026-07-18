"""Parity tests for single-sourced worker agent definitions."""

import re

import pytest

from installer.manifest import MANIFEST, Manifest
from installer.parity import validate
from installer.render import generated_path, render_worker, sync_workers

PLATFORMS = ('claude', 'copilot')


def test_rendered_matches_committed_files(repo_root):
    for name in MANIFEST.workers:
        for platform in PLATFORMS:
            path = generated_path(name, platform, repo_root)
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


def test_scout_and_analyst_carry_plan_mode_caveat():
    phrase = (
        'if workspace writes are blocked, as in plan mode, '
        'return the evidence inline and note that'
    )
    for name in ('scout', 'code-analyst'):
        for platform in PLATFORMS:
            normalized = ' '.join(render_worker(name, platform).split())
            assert phrase in normalized, (name, platform)


@pytest.fixture
def seed_shared_bodies(repo_root):
    def _seed(root, names):
        (root / 'shared' / 'agents').mkdir(parents=True, exist_ok=True)
        for name in names:
            source = repo_root / 'shared' / 'agents' / f'{name}.md'
            (root / 'shared' / 'agents' / f'{name}.md').write_text(
                source.read_text(encoding='utf-8'), encoding='utf-8'
            )

    return _seed


def test_sync_workers_idempotent(tmp_path, seed_shared_bodies):
    seed_shared_bodies(tmp_path, MANIFEST.workers)
    first = sync_workers(tmp_path)
    contents_first = {p: p.read_text(encoding='utf-8') for p in first}
    second = sync_workers(tmp_path)
    contents_second = {p: p.read_text(encoding='utf-8') for p in second}
    assert first == second
    assert contents_first == contents_second


def test_injected_manifest_overrides_default(tmp_path, seed_shared_bodies):
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
    seed_shared_bodies(tmp_path, fake.workers)
    rendered = render_worker('scout', 'claude', manifest=fake)
    assert 'model: fake-model' in rendered
    assert 'model: haiku' not in rendered

    written = sync_workers(tmp_path, manifest=fake)
    assert len(written) == 4
    implementer_out = (tmp_path / 'agents' / 'implementer.md').read_text(encoding='utf-8')
    assert 'FAKE RULE.' in implementer_out
    assert 'MANIFEST' not in implementer_out


def test_manifest_hook_files_exist(repo_root):
    for name in (*MANIFEST.claude_hooks, *MANIFEST.copilot_hooks):
        assert (repo_root / 'hooks' / name).is_file(), name


def test_render_worker_honors_root(repo_copy):
    body = repo_copy / 'shared' / 'agents' / 'scout.md'
    body.write_text(body.read_text(encoding='utf-8') + '\nExtra root sentence.\n')

    assert 'Extra root sentence.' in render_worker('scout', 'claude', root=repo_copy)
    assert 'Extra root sentence.' not in render_worker('scout', 'claude')


def test_validate_clean_tree(repo_copy):
    assert validate(repo_copy) == []


def test_validate_detects_generated_drift(repo_copy):
    drifted = repo_copy / 'agents' / 'scout.md'
    drifted.write_text(drifted.read_text(encoding='utf-8') + 'x\n')

    findings = validate(repo_copy)

    assert len(findings) == 1
    assert 'agents/scout.md' in findings[0]


def test_validate_detects_criteria_drift(repo_copy):
    target = repo_copy / 'skills' / 'agentmaster-review' / 'SKILL.md'
    text = target.read_text(encoding='utf-8')
    start = '<!-- agentmaster:criteria:start -->'
    target.write_text(text.replace(start, start + '\ninjected drift line'))

    findings = validate(repo_copy)

    assert any('agentmaster-review/SKILL.md' in f for f in findings)


def test_validate_detects_missing_shared_body(repo_copy):
    (repo_copy / 'shared' / 'agents' / 'scout.md').unlink()

    findings = validate(repo_copy)

    assert any('shared/agents/scout.md' in f for f in findings)


def test_validate_detects_stray_worker_file(repo_copy):
    (repo_copy / 'agents' / 'rogue.md').write_text('---\nname: rogue\n---\n\nrogue\n')

    findings = validate(repo_copy)

    assert any('rogue.md' in f for f in findings)


def test_validate_with_injected_manifest(tmp_path):
    fake = Manifest(
        workers=('w',),
        claude_skills=(),
        copilot_coordinators=(),
        claude_only_agents=(),
        claude_hooks=(),
        copilot_hooks=(),
        claude_frontmatter={'w': 'name: w\nmodel: haiku\n'},
        copilot_frontmatter={'w': 'name: w\nmodel: claude-haiku-4.5\n'},
        substitutions={},
    )
    root = tmp_path / 'fake-root'
    (root / 'shared' / 'agents').mkdir(parents=True)
    (root / 'shared' / 'agents' / 'w.md').write_text('Fake body.\n')
    sync_workers(root, fake)

    assert validate(root, fake) == []


@pytest.mark.subprocess
def test_cli_install_dry_run_writes_nothing(tmp_path, run_cli, repo_root):
    claude_home = tmp_path / 'claude-home'
    copilot_home = tmp_path / 'copilot-home'

    result = run_cli(
        ['install', '--target', 'all', '--dry-run'],
        cwd=repo_root,
        env_extra={
            'CLAUDE_CONFIG_DIR': str(claude_home),
            'COPILOT_CONFIG_DIR': str(copilot_home),
        },
    )

    assert result.returncode == 0, result.stderr
    assert 'create' in result.stdout
    assert not claude_home.exists()
    assert not copilot_home.exists()


@pytest.mark.subprocess
def test_cli_validate_clean_exits_zero(run_cli, repo_root):
    result = run_cli(['validate', '--target', 'all'], cwd=repo_root)

    assert result.returncode == 0, result.stderr


@pytest.mark.subprocess
def test_cli_validate_drift_exits_one(repo_copy, run_cli):
    drifted = repo_copy / 'agents' / 'scout.md'
    drifted.write_text(drifted.read_text(encoding='utf-8') + 'x\n')

    result = run_cli(['validate', '--target', 'all'], cwd=repo_copy)

    assert result.returncode == 1
    assert 'scout.md' in result.stdout + result.stderr


@pytest.mark.subprocess
def test_cli_sync_is_idempotent_on_clean_tree(repo_copy, run_cli):
    result = run_cli(['sync'], cwd=repo_copy)

    assert result.returncode == 0, result.stderr
    assert validate(repo_copy) == []


@pytest.mark.subprocess
def test_cli_rejects_invalid_model(run_cli, repo_root):
    result = run_cli(
        ['install', '--target', 'claude', '--model', 'bad model!', '--dry-run'],
        cwd=repo_root,
    )

    assert result.returncode != 0
    assert 'model' in (result.stdout + result.stderr).lower()
