"""Tests for `installer.skill_routing` — deterministic writing-skills routing."""

from installer.capabilities import (
    CAPABILITIES,
    check_tool_authority,
    validate_frontmatter,
)
from installer.plan_parser import parse_tasks
from installer.skill_routing import route

TRIGGERING_PLAN = """\
## Tasks

**T1 — add a checklist to a coordinator skill** implementer (sonnet)
Scope: skills/agentmaster-execute/SKILL.md, copilot/agents/agentmaster-execute.agent.md
Uses: writing-skills
Verify: `pytest tests/test_parity.py`
"""

NON_TRIGGERING_PLAN = """\
## Tasks

**T1 — add ledger transaction retries** implementer (sonnet)
Scope: ledger/connection.py, tests/test_ledger_transactions.py
Uses: writing-skills
Verify: `pytest`
"""

UNTAGGED_SKILL_TOUCH_PLAN = """\
## Tasks

**T1 — reword the plan skill prose** implementer (sonnet)
Scope: skills/agentmaster-plan/SKILL.md
Uses: none
Verify: `pytest tests/test_parity.py`
"""


def test_routes_when_requested_and_scope_touches_skill_files():
    task = parse_tasks(TRIGGERING_PLAN)[0]

    decision = route(task)

    assert decision.requested is True
    assert decision.triggered is True
    assert decision.routed is True
    assert decision.mismatch is False


def test_does_not_route_when_requested_but_scope_is_unrelated():
    task = parse_tasks(NON_TRIGGERING_PLAN)[0]

    decision = route(task)

    assert decision.requested is True
    assert decision.triggered is False
    assert decision.routed is False
    assert decision.mismatch is True
    assert 'T1' in decision.reason


def test_does_not_route_when_scope_touches_skill_files_but_not_requested():
    task = parse_tasks(UNTAGGED_SKILL_TOUCH_PLAN)[0]

    decision = route(task)

    assert decision.requested is False
    assert decision.triggered is True
    assert decision.routed is False
    assert decision.mismatch is True


def test_capability_registry_has_writing_skills_with_checklist():
    capability = CAPABILITIES['writing-skills']

    assert capability.name == 'writing-skills'
    assert 'trigger' in capability.checklist.lower()
    assert 'least authority' in capability.checklist.lower()


def test_validate_frontmatter_flags_missing_required_keys():
    errors = validate_frontmatter('name: foo\n', platform='claude')

    assert any('description' in e for e in errors)
    assert any('model' in e for e in errors)


def test_validate_frontmatter_passes_complete_block():
    complete = 'name: foo\ndescription: does a thing\nmodel: sonnet\n'

    assert validate_frontmatter(complete, platform='claude') == []
    assert validate_frontmatter(complete, platform='copilot') == []


def test_check_tool_authority_flags_tools_outside_least_authority():
    capability = CAPABILITIES['writing-skills']

    errors = check_tool_authority(('Read', 'Edit', 'Bash'), capability.allowed_tools)

    assert len(errors) == 1
    assert 'Bash' in errors[0]


def test_check_tool_authority_passes_within_bounds():
    capability = CAPABILITIES['writing-skills']

    assert check_tool_authority(('Read', 'Edit'), capability.allowed_tools) == []
