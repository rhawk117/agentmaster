import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

ALLOWED_KEYS = frozenset({'model', 'effort'})

_DELIMITER = '---'
_TOP_LEVEL_KEY_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_-]*):(.*)$')
_UNSAFE_VALUE_RE = re.compile(r'^\s*[&*!]')


class FrontmatterError(ValueError): ...


def _is_delimiter(line: str) -> bool:
    return line.rstrip('\r\n') == _DELIMITER


def _validate_overrides(overrides: Mapping[str, str]) -> None:
    unknown = sorted(set(overrides) - ALLOWED_KEYS)
    if unknown:
        raise FrontmatterError(f'not allow-listed: {unknown}')
    for key, value in overrides.items():
        if '\n' in value or '\r' in value:
            raise FrontmatterError(f'{key}: override value must be a single line')


def _split_frontmatter(lines: list[str]) -> tuple[list[str], list[str]]:
    if not lines or not _is_delimiter(lines[0]):
        raise FrontmatterError('missing opening --- delimiter')
    closing = next((i for i in range(1, len(lines)) if _is_delimiter(lines[i])), None)
    if closing is None:
        raise FrontmatterError('missing closing --- delimiter')
    return lines[1:closing], lines[closing:]


def _managed_key_lines(block: list[str]) -> dict[str, int]:
    seen: dict[str, int] = {}
    for index, line in enumerate(block):
        match = _TOP_LEVEL_KEY_RE.match(line)
        if match is None or match.group(1) not in ALLOWED_KEYS:
            continue
        key = match.group(1)
        if key in seen:
            raise FrontmatterError(f'duplicate managed key: {key}')
        seen[key] = index
        if _UNSAFE_VALUE_RE.match(match.group(2)):
            raise FrontmatterError(f'{key}: refusing to edit an anchor/alias/tag value')
    return seen


def update_frontmatter(content: str, overrides: Mapping[str, str]) -> str:
    _validate_overrides(overrides)
    lines = content.splitlines(keepends=True)
    block, rest = _split_frontmatter(lines)
    seen = _managed_key_lines(block)

    for key, value in overrides.items():
        rendered = f'{key}: {value}'
        if key in seen:
            newline = '\n' if block[seen[key]].endswith('\n') else ''
            block[seen[key]] = rendered + newline
        else:
            block.append(rendered + '\n')

    return ''.join([lines[0], *block, *rest])
