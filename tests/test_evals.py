"""Schema guard for evals/evals.json — the first CI consumer of evals/.

evals.json is a wrapper object (`{"skill_name": ..., "evals": [...]}`), not a
bare array. This validates required fields and types per case and that every
`files` entry resolves — every case in the file today references only input
fixtures that exist on disk, so an unresolved path is a real defect.
"""

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

REQUIRED_FIELDS: dict[str, type] = {
    'id': int,
    'eval_name': str,
    'prompt': str,
    'expected_output': str,
    'files': list,
    'assertions': list,
}


def _load_evals(repo_root: Path) -> dict:
    path = repo_root / 'evals' / 'evals.json'
    return json.loads(path.read_text(encoding='utf-8'))


def test_evals_json_is_a_wrapper_object(repo_root: Path) -> None:
    data = _load_evals(repo_root)

    assert isinstance(data, dict)
    assert isinstance(data.get('skill_name'), str)
    assert isinstance(data.get('evals'), list)
    assert data['evals']


def test_every_case_has_required_fields_with_correct_types(repo_root: Path) -> None:
    data = _load_evals(repo_root)

    for case in data['evals']:
        for field, expected_type in REQUIRED_FIELDS.items():
            assert field in case, (case.get('id'), field)
            assert isinstance(case[field], expected_type), (case.get('id'), field)


def test_case_ids_are_unique(repo_root: Path) -> None:
    data = _load_evals(repo_root)

    ids = [case['id'] for case in data['evals']]
    assert len(ids) == len(set(ids))


def test_every_files_entry_exists(repo_root: Path) -> None:
    data = _load_evals(repo_root)

    for case in data['evals']:
        for relative in case['files']:
            assert (repo_root / relative).is_file(), (case['id'], relative)


def test_every_assertion_is_a_nonempty_string(repo_root: Path) -> None:
    data = _load_evals(repo_root)

    for case in data['evals']:
        for assertion in case['assertions']:
            assert isinstance(assertion, str)
            assert assertion.strip()
