"""Read the on-disk spool of hook events pending ledger ingestion (SPEC.md §16.1, §19).

Hook processes never import the `ledger` package: they run standalone,
copied without it, alongside only `hooklib.py` (see `installer/manifest.py`).
`hooklib.spool_event` writes a small versioned JSON file per event instead;
this module reads and validates that same wire format so `ledger.ingestion`
can normalize it into typed rows. Malformed files are reported, never
raised, matching the fail-open posture the hook side already holds.
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SpooledEvent:
    """One parsed, validated event read from the spool directory."""

    path: Path
    kind: str
    harness_session_id: str
    fields: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SpoolReadResult:
    """Every event parsed from one `read_events` call, and which files failed to parse."""

    events: tuple[SpooledEvent, ...]
    malformed: tuple[Path, ...]


def _parse(path: Path) -> SpooledEvent | None:
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except OSError, ValueError:
        return None
    if not isinstance(record, dict):
        return None
    if record.get('schema_version') != SCHEMA_VERSION:
        return None
    kind = record.get('kind')
    harness_session_id = record.get('harness_session_id')
    if not isinstance(kind, str) or not isinstance(harness_session_id, str):
        return None
    fields = {
        key: value
        for key, value in record.items()
        if key not in ('schema_version', 'kind', 'harness_session_id')
    }
    return SpooledEvent(
        path=path, kind=kind, harness_session_id=harness_session_id, fields=fields
    )


def read_events(spool_dir: Path) -> SpoolReadResult:
    """Parse every `*.json` spool file, oldest first; report malformed ones separately."""
    if not spool_dir.is_dir():
        return SpoolReadResult((), ())
    events: list[SpooledEvent] = []
    malformed: list[Path] = []
    for path in sorted(spool_dir.glob('*.json')):
        parsed = _parse(path)
        if parsed is None:
            malformed.append(path)
        else:
            events.append(parsed)
    return SpoolReadResult(tuple(events), tuple(malformed))


def discard(paths: tuple[Path, ...] | list[Path]) -> None:
    """Remove spool files that have been durably ingested (or can never be)."""
    for path in paths:
        path.unlink(missing_ok=True)
