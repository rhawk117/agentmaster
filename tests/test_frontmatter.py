import pytest

from installer.frontmatter import ALLOWED_KEYS, FrontmatterError, update_frontmatter

DOC = '---\nname: co\nmodel: placeholder\n---\nbody\ntext\n'


def test_replaces_existing_managed_key_preserving_everything_else():
    updated = update_frontmatter(DOC, {'model': 'opus'})

    assert updated == '---\nname: co\nmodel: opus\n---\nbody\ntext\n'


def test_inserts_missing_managed_key():
    doc = '---\nname: co\n---\nbody\n'

    updated = update_frontmatter(doc, {'effort': 'high'})

    assert updated == '---\nname: co\neffort: high\n---\nbody\n'


def test_body_is_byte_for_byte_preserved():
    body = 'body\n\n## Heading\n- a list item\nmodel: not a key here\n'
    doc = f'---\nname: co\n---\n{body}'

    updated = update_frontmatter(doc, {'model': 'opus'})

    assert updated.endswith(body)


def test_comments_and_nested_structures_are_preserved():
    doc = (
        '---\n'
        'name: co\n'
        'model: opus  # inline comment\n'
        'hooks:\n'
        '  PreToolUse:\n'
        '    - matcher: "Read"\n'
        '---\n'
        'body\n'
    )

    updated = update_frontmatter(doc, {'effort': 'low'})

    assert 'model: opus  # inline comment\n' in updated
    assert 'hooks:\n' in updated
    assert '  PreToolUse:\n' in updated
    assert '    - matcher: "Read"\n' in updated
    assert 'effort: low\n' in updated


def test_field_order_is_preserved_for_untouched_keys():
    doc = '---\nname: co\ndescription: d\nmodel: old\ntools: x\n---\nbody\n'

    updated = update_frontmatter(doc, {'model': 'new'})

    lines = updated.splitlines()
    assert lines == [
        '---',
        'name: co',
        'description: d',
        'model: new',
        'tools: x',
        '---',
        'body',
    ]


def test_rejects_key_not_allow_listed():
    with pytest.raises(FrontmatterError, match='not allow-listed'):
        update_frontmatter(DOC, {'tools': 'x'})


def test_rejects_multiline_override_value():
    with pytest.raises(FrontmatterError, match='single line'):
        update_frontmatter(DOC, {'model': 'a\nb'})


def test_rejects_missing_opening_delimiter():
    with pytest.raises(FrontmatterError, match='opening'):
        update_frontmatter('no delimiter here\nmodel: x\n', {'model': 'a'})


def test_rejects_missing_closing_delimiter():
    with pytest.raises(FrontmatterError, match='closing'):
        update_frontmatter('---\nname: co\nmodel: x\n', {'model': 'a'})


def test_rejects_duplicate_managed_key():
    doc = '---\nmodel: a\nmodel: b\n---\nbody\n'

    with pytest.raises(FrontmatterError, match='duplicate managed key'):
        update_frontmatter(doc, {'model': 'c'})


@pytest.mark.parametrize('bad_value', ['&anchor opus', '*anchor', '!!str opus'])
def test_rejects_anchor_alias_or_tag_on_managed_key(bad_value):
    doc = f'---\nmodel: {bad_value}\n---\nbody\n'

    with pytest.raises(FrontmatterError, match='anchor/alias/tag'):
        update_frontmatter(doc, {'model': 'opus'})


def test_never_edits_outside_the_frontmatter_block():
    doc = '---\nname: co\n---\nmodel: this is body text, not frontmatter\n'

    updated = update_frontmatter(doc, {'model': 'opus'})

    assert 'model: this is body text, not frontmatter\n' in updated
    assert updated.count('model:') == 2


def test_no_global_regex_can_rewrite_body_content():
    doc = '---\nname: co\nmodel: old\n---\nExample: `model: whatever` in prose.\n'

    updated = update_frontmatter(doc, {'model': 'new'})

    assert 'model: new\n' in updated
    assert 'Example: `model: whatever` in prose.\n' in updated


def test_allowed_keys_are_model_and_effort():
    assert frozenset({'model', 'effort'}) == ALLOWED_KEYS
