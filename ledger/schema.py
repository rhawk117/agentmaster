import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

_MIGRATIONS_DIR = Path(__file__).parent / 'migrations'
_SQL_TOKEN = re.compile(r"--[^\n]*|'(?:[^']|'')*'|;|\w+|.", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Migration:
    to_version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


def _split_statements(script: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    depth = 0
    for token in _SQL_TOKEN.findall(script):
        buffer.append(token)
        if token.startswith('--'):
            continue
        word = token.lower()
        if word == 'begin':
            depth += 1
        elif word == 'end':
            depth = max(0, depth - 1)
        elif token == ';' and depth == 0:
            statement = ''.join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
    tail = ''.join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _apply_sql_file(sql_path: Path) -> Callable[[sqlite3.Connection], None]:
    script = sql_path.read_text(encoding='utf-8')
    statements = _split_statements(script)

    def _apply(connection: sqlite3.Connection) -> None:
        for statement in statements:
            connection.execute(statement)

    return _apply


def _discover_migrations(migrations_dir: Path) -> tuple[Migration, ...]:
    migrations = []
    for entry in sorted(migrations_dir.iterdir()):
        if not entry.is_dir():
            continue
        prefix, _, name = entry.name.partition('_')
        migrations.append(
            Migration(
                to_version=int(prefix),
                description=name.replace('_', ' '),
                apply=_apply_sql_file(entry / 'upgrade.sql'),
            )
        )
    return tuple(migrations)


MIGRATIONS: tuple[Migration, ...] = _discover_migrations(_MIGRATIONS_DIR)
SUPPORTED_SCHEMA_VERSION = MIGRATIONS[-1].to_version
