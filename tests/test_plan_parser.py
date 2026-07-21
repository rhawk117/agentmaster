"""Tests for `installer.plan_parser` — structured `Uses:` metadata parsing."""

import pytest

from installer.plan_parser import UnknownCapabilityError, parse_tasks, validate_uses

PLAN_WITH_WRITING_SKILLS = """\
## Tasks

**T1 — add a new SKILL.md** implementer (sonnet)
Scope: skills/agentmaster-plan/SKILL.md, tests/test_plan_lint.py
Uses: writing-skills
Verify: `pytest`

**T2 — fix a ledger migration** implementer (sonnet)
Scope: ledger/migrations/0002_init.sql
Uses: none
Verify: `pytest`

**T3 — add CLI validation** implementer (sonnet)
Scope: agentmaster/cli.py
Uses: superpowers:test-driven-development
Verify: `pytest`
"""

PLAN_WITH_UNKNOWN_CAPABILITY = """\
## Tasks

**T1 — do a thing** implementer (sonnet)
Scope: agentmaster/cli.py
Uses: not-a-real-capability
Verify: `pytest`
"""


def test_parse_tasks_extracts_id_title_scope_and_uses():
    tasks = parse_tasks(PLAN_WITH_WRITING_SKILLS)

    assert [t.task_id for t in tasks] == ['T1', 'T2', 'T3']
    assert tasks[0].title == 'add a new SKILL.md'
    assert tasks[0].uses == ('writing-skills',)
    assert 'skills/agentmaster-plan/SKILL.md' in tasks[0].scope
    assert tasks[1].uses == ('none',)
    assert tasks[2].uses == ('superpowers:test-driven-development',)


def test_parse_tasks_on_empty_tasks_section_returns_empty_list():
    assert parse_tasks('## Tasks\n\nnone\n') == []


def test_validate_uses_accepts_known_capability_none_and_namespaced_tokens():
    tasks = parse_tasks(PLAN_WITH_WRITING_SKILLS)

    assert validate_uses(tasks) == []


def test_validate_uses_rejects_unknown_bare_capability():
    tasks = parse_tasks(PLAN_WITH_UNKNOWN_CAPABILITY)

    errors = validate_uses(tasks)

    assert len(errors) == 1
    assert 'T1' in errors[0]
    assert 'not-a-real-capability' in errors[0]


def test_validate_uses_accepts_repo_skill_names():
    plan = """\
## Tasks

**T1 — do a thing** implementer (sonnet)
Scope: skills/agentmaster-review/SKILL.md
Uses: agentmaster-review
Verify: `pytest`
"""
    assert validate_uses(parse_tasks(plan)) == []


def test_unknown_capability_error_is_raiseable_with_task_context():
    with pytest.raises(UnknownCapabilityError) as excinfo:
        raise UnknownCapabilityError(task_id='T1', capability='bogus')

    assert 'T1' in str(excinfo.value)
    assert 'bogus' in str(excinfo.value)
