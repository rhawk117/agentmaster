"""Idempotent ENTRYPOINT registry seeding (SPEC.md §17.1, §19, §23 Microtask 19).

`skill`/`agent`/`hook` rows come from `installer.manifest.MANIFEST`; `command`
rows come from `agentmaster.registry.COMMAND_REGISTRY` (the manifest carries
no command list). Seeding never deletes a row: a `(kind, name)` no longer
named by either source is deactivated (`active=0`) rather than removed, so
provenance for past sessions/tool calls that reference it survives.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentmaster.registry import COMMAND_REGISTRY, CommandEntry
from installer.manifest import MANIFEST, Manifest
from ledger.transactions import run_write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

__all__ = ['EntrypointSeedReport', 'seed_entrypoints']


@dataclass(frozen=True, slots=True)
class _DesiredEntrypoint:
    """One entrypoint this call wants present and active."""

    kind: str
    name: str
    source_path: str


def _desired_entrypoints(
    manifest: Manifest, command_registry: tuple[CommandEntry, ...]
) -> list[_DesiredEntrypoint]:
    agent_names = dict.fromkeys((*manifest.workers, *manifest.claude_only_agents))
    hook_names = dict.fromkeys((*manifest.claude_hooks, *manifest.copilot_hooks))
    return [
        *(
            _DesiredEntrypoint('skill', name, f'skills/{name}/SKILL.md')
            for name in manifest.claude_skills
        ),
        *(_DesiredEntrypoint('agent', name, f'agents/{name}.md') for name in agent_names),
        *(_DesiredEntrypoint('hook', name, f'hooks/{name}') for name in hook_names),
        *(
            _DesiredEntrypoint(
                'command', f'{entry.group} {entry.name}', 'agentmaster/registry.py'
            )
            for entry in command_registry
        ),
    ]


@dataclass(frozen=True, slots=True)
class EntrypointSeedReport:
    """Counts of rows one `seed_entrypoints` call inserted/updated/deactivated."""

    inserted: int
    updated: int
    deactivated: int


def seed_entrypoints(
    connection: sqlite3.Connection,
    *,
    id_factory: Callable[[], str],
    now: Callable[[], str],
    manifest: Manifest = MANIFEST,
    command_registry: tuple[CommandEntry, ...] = COMMAND_REGISTRY,
) -> EntrypointSeedReport:
    """Idempotently seed ENTRYPOINT rows from `manifest` and `command_registry`.

    A `(kind, name)` not yet present is inserted active; an existing row
    whose `source_path` drifted or that was previously deactivated is
    updated in place and reactivated; an active row no longer named by
    either source is deactivated. Calling this twice with unchanged inputs
    makes no writes.
    """
    desired = _desired_entrypoints(manifest, command_registry)
    desired_keys = {(row.kind, row.name) for row in desired}

    def _op(conn: sqlite3.Connection) -> EntrypointSeedReport:
        existing = {
            (kind, name): (row_id, source_path, bool(active))
            for row_id, kind, name, source_path, active in conn.execute(
                'SELECT id, kind, name, source_path, active FROM ENTRYPOINT'
            ).fetchall()
        }
        inserted = updated = deactivated = 0
        for row in desired:
            current = existing.get((row.kind, row.name))
            if current is None:
                conn.execute(
                    'INSERT INTO ENTRYPOINT (id, kind, name, source_path, active, '
                    'created_at) VALUES (?, ?, ?, ?, 1, ?)',
                    (id_factory(), row.kind, row.name, row.source_path, now()),
                )
                inserted += 1
                continue
            row_id, source_path, active = current
            if source_path != row.source_path or not active:
                conn.execute(
                    'UPDATE ENTRYPOINT SET source_path = ?, active = 1 WHERE id = ?',
                    (row.source_path, row_id),
                )
                updated += 1
        for (kind, name), (row_id, _source_path, active) in existing.items():
            if active and (kind, name) not in desired_keys:
                conn.execute('UPDATE ENTRYPOINT SET active = 0 WHERE id = ?', (row_id,))
                deactivated += 1
        return EntrypointSeedReport(
            inserted=inserted, updated=updated, deactivated=deactivated
        )

    return run_write_transaction(connection, _op)
