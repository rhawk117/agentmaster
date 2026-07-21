"""The `agentmaster` CLI's own registered-command table (SPEC.md §17.1, §19).

A structured, queryable registry of this CLI's command groups and verbs.
Microtask 19 seeds `kind='command'` ENTRYPOINT rows (SPEC.md §17.1) from
`COMMAND_REGISTRY`; this module only defines the registry itself.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandEntry:
    """One registered `agentmaster` command: its group, verb, and description."""

    group: str
    name: str
    description: str


COMMAND_REGISTRY: tuple[CommandEntry, ...] = (
    CommandEntry(
        group='ledger',
        name='init',
        description='Create the ledger at the latest schema version.',
    ),
    CommandEntry(
        group='ledger',
        name='migrate',
        description='Apply pending migrations to an existing ledger.',
    ),
    CommandEntry(
        group='ledger', name='backup', description='Write a consistent ledger backup.'
    ),
    CommandEntry(
        group='ledger',
        name='doctor',
        description='Report ledger health without mutating it.',
    ),
    CommandEntry(
        group='ledger',
        name='record-feedback',
        description='Record a FEEDBACK row for a run/task/memory.',
    ),
    CommandEntry(
        group='ledger',
        name='query-entrypoints',
        description='List ENTRYPOINT rows.',
    ),
    CommandEntry(
        group='ledger',
        name='query-runs',
        description='List RUN rows via v_run_summary.',
    ),
    CommandEntry(
        group='ledger',
        name='query-tokens',
        description='List per-run, per-model token totals.',
    ),
    CommandEntry(
        group='ledger',
        name='ingest-events',
        description='Drain the spooled hook-event queue into ledger rows.',
    ),
    CommandEntry(
        group='migrate',
        name='legacy-files',
        description='One-shot import of pre-v2 Agentmaster artifacts into the ledger.',
    ),
    CommandEntry(
        group='memory',
        name='search',
        description='Search active/validated memories by full-text query.',
    ),
    CommandEntry(group='memory', name='show', description='Show one memory by id.'),
    CommandEntry(
        group='memory',
        name='validate',
        description='Transition a Candidate memory to Validated.',
    ),
    CommandEntry(
        group='memory',
        name='activate',
        description='Transition a Validated memory to Active.',
    ),
    CommandEntry(
        group='memory',
        name='supersede',
        description='Supersede an Active memory with a new one.',
    ),
    CommandEntry(
        group='memory',
        name='reject',
        description='Reject a Candidate or Active memory.',
    ),
    CommandEntry(
        group='context',
        name='build',
        description='Build a bounded, session-scoped context pack.',
    ),
    CommandEntry(
        group='delivery',
        name='prepare-pr',
        description='Stage, commit, push, and open/reconcile a PR via the git publisher.',
    ),
    CommandEntry(
        group='delivery',
        name='watch-ci',
        description='Poll required checks and advance CIPending to ReviewRequired.',
    ),
    CommandEntry(
        group='delivery',
        name='review-gate',
        description='Verify PR/CI/reviewed-SHA match and unresolved findings.',
    ),
    CommandEntry(
        group='delivery',
        name='merge-gate',
        description='Repeat the review-gate checks and merge on an exact head match.',
    ),
)


def find_command(*, group: str, name: str) -> CommandEntry | None:
    """Return the registered command matching `group`/`name`, or `None`."""
    for entry in COMMAND_REGISTRY:
        if entry.group == group and entry.name == name:
            return entry
    return None
