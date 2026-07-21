"""The unified `agentmaster` command surface (SPEC.md §19, §23 Microtask 16).

Parses arguments and formats JSON/text output only; all ledger reads/writes
live in `ledger.*` modules so they stay directly testable without a
subprocess. `ledger.cli` still owns init/migrate/backup/doctor; this module
delegates to it and adds the remaining §19 ledger/memory/context verbs.
"""

import argparse
import json
import sys
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ledger import cli as ledger_cli
from ledger.connection import connect
from ledger.context_pack import (
    ContextPackRequest,
    RunNotFoundError,
    SessionScopeError,
    TaskNotFoundError,
    build_context_pack,
)
from ledger.feedback import FeedbackInput, UnknownReferenceError, record_feedback
from ledger.memory_service import (
    IllegalMemoryTransitionError,
    MemoryAccessLog,
    MemoryNotFoundError,
    MemorySearchScope,
    NewMemoryInput,
    activate_memory,
    reject_memory,
    search_memories,
    show_memory,
    supersede_memory,
    validate_memory,
)
from ledger.queries import query_entrypoints

if TYPE_CHECKING:
    from collections.abc import Callable


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _emit(*, json_output: bool, payload: object, text_lines: list[str]) -> None:
    if json_output:
        print(json.dumps(payload))
        return
    for line in text_lines:
        print(line)


# --- ledger group ----------------------------------------------------------


def _cmd_ledger_init(args: argparse.Namespace) -> int:
    return ledger_cli.cmd_init(Path(args.path))


def _cmd_ledger_migrate(args: argparse.Namespace) -> int:
    return ledger_cli.cmd_migrate(Path(args.path))


def _cmd_ledger_backup(args: argparse.Namespace) -> int:
    return ledger_cli.cmd_backup(Path(args.path), Path(args.destination))


def _cmd_ledger_doctor(args: argparse.Namespace) -> int:
    return ledger_cli.cmd_doctor(Path(args.path), json_output=args.json_output)


def _cmd_ledger_record_feedback(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    feedback = FeedbackInput(
        id=str(uuid.uuid4()),
        user_session_id=args.user_session_id,
        run_id=args.run_id,
        rating=args.rating,
        created_at=_now(),
        task_id=args.task_id,
        memory_id=args.memory_id,
        comment=args.comment,
    )
    try:
        record_feedback(connection, feedback)
    except (ValueError, UnknownReferenceError) as error:
        print(f'ledger record-feedback: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(feedback.id)
    return 0


def _cmd_ledger_query_entrypoints(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        rows = query_entrypoints(connection)
    finally:
        connection.close()
    text_lines = (
        ['no entrypoints recorded']
        if not rows
        else [
            f'{row.kind:8} {row.name:24} active={row.active} {row.source_path or ""}'
            for row in rows
        ]
    )
    _emit(
        json_output=args.json_output,
        payload=[asdict(row) for row in rows],
        text_lines=text_lines,
    )
    return 0


# --- memory group ------------------------------------------------------------


def _cmd_memory_search(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        scope = MemorySearchScope(
            project_id=args.project_id,
            run_id=args.run_id,
            task_id=args.task_id,
            agent_session_id=args.agent_session_id,
        )
        results = search_memories(
            connection,
            scope,
            args.query,
            MemoryAccessLog(
                access_id_factory=lambda: str(uuid.uuid4()), created_at=_now()
            ),
            limit=args.limit,
        )
    finally:
        connection.close()
    text_lines = (
        ['no matching memories']
        if not results
        else [
            f'#{result.rank} {result.memory_id} score={result.score:.3f} '
            f'tokens~{result.estimated_tokens} {result.title}'
            for result in results
        ]
    )
    _emit(
        json_output=args.json_output,
        payload=[asdict(result) for result in results],
        text_lines=text_lines,
    )
    return 0


def _cmd_memory_show(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        detail = show_memory(connection, args.memory_id)
    finally:
        connection.close()
    if detail is None:
        print(f'memory {args.memory_id!r} not found', file=sys.stderr)
        return 1
    _emit(
        json_output=args.json_output,
        payload=asdict(detail),
        text_lines=[
            f'{detail.memory_id} [{detail.state}] {detail.title}',
            detail.content,
        ],
    )
    return 0


def _cmd_memory_validate(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        validate_memory(
            connection,
            args.memory_id,
            args.evidence_id,
            updated_at=_now(),
            validating_session_id=args.validating_session_id,
        )
    except (MemoryNotFoundError, IllegalMemoryTransitionError) as error:
        print(f'memory validate: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


def _cmd_memory_activate(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        activate_memory(connection, args.memory_id, updated_at=_now())
    except (MemoryNotFoundError, IllegalMemoryTransitionError) as error:
        print(f'memory activate: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


def _cmd_memory_reject(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        reject_memory(connection, args.memory_id, updated_at=_now())
    except (MemoryNotFoundError, IllegalMemoryTransitionError) as error:
        print(f'memory reject: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


def _cmd_memory_supersede(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    new_memory = NewMemoryInput(
        id=args.new_memory_id,
        origin_project_id=args.project_id,
        memory_kind=args.memory_kind,
        title=args.title,
        content=args.content,
        confidence=args.confidence,
    )
    try:
        supersede_memory(connection, args.old_memory_id, new_memory, updated_at=_now())
    except (MemoryNotFoundError, IllegalMemoryTransitionError) as error:
        print(f'memory supersede: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(new_memory.id)
    return 0


# --- context group -----------------------------------------------------------


def _cmd_context_build(args: argparse.Namespace) -> int:
    connection = connect(Path(args.path))
    try:
        request = ContextPackRequest(
            project_id=args.project_id,
            user_session_id=args.user_session_id,
            run_id=args.run_id,
            task_id=args.task_id,
            budget_tokens=args.budget_tokens,
            query=args.query,
        )
        pack = build_context_pack(connection, request, created_at=_now())
    except (SessionScopeError, RunNotFoundError, TaskNotFoundError) as error:
        print(f'context build: {error}', file=sys.stderr)
        return 1
    finally:
        connection.close()
    text_lines = [
        f'task {pack.task_id}: {pack.objective}',
        f'budget {pack.estimated_tokens}/{pack.budget_tokens} tokens',
        *[f'  #{m.rank} {m.memory_id} {m.title}' for m in pack.selected_memories],
    ]
    if pack.stop_conditions:
        text_lines.append(f'stop conditions: {", ".join(pack.stop_conditions)}')
    text_lines.append(f'digest {pack.digest}')
    _emit(json_output=args.json_output, payload=asdict(pack), text_lines=text_lines)
    return 0


# --- argument parsing --------------------------------------------------------


def _add_path_argument(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument('--path', required=True)


def _add_json_argument(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument('--json', action='store_true', dest='json_output')


def _build_ledger_subparser(sub: argparse._SubParsersAction) -> dict[str, Callable]:
    ledger_parser = sub.add_parser('ledger')
    ledger_sub = ledger_parser.add_subparsers(dest='command', required=True)

    for name in ('init', 'migrate'):
        _add_path_argument(ledger_sub.add_parser(name))

    doctor_cmd = ledger_sub.add_parser('doctor')
    _add_path_argument(doctor_cmd)
    _add_json_argument(doctor_cmd)

    backup_cmd = ledger_sub.add_parser('backup')
    _add_path_argument(backup_cmd)
    backup_cmd.add_argument('--destination', required=True)

    feedback_cmd = ledger_sub.add_parser('record-feedback')
    _add_path_argument(feedback_cmd)
    feedback_cmd.add_argument('--user-session-id', required=True)
    feedback_cmd.add_argument('--run-id', required=True)
    feedback_cmd.add_argument('--rating', type=int, choices=(-1, 0, 1), required=True)
    feedback_cmd.add_argument('--task-id', default=None)
    feedback_cmd.add_argument('--memory-id', default=None)
    feedback_cmd.add_argument('--comment', default=None)

    query_cmd = ledger_sub.add_parser('query')
    query_sub = query_cmd.add_subparsers(dest='query_target', required=True)
    entrypoints_cmd = query_sub.add_parser('entrypoints')
    _add_path_argument(entrypoints_cmd)
    _add_json_argument(entrypoints_cmd)

    return {
        'init': _cmd_ledger_init,
        'migrate': _cmd_ledger_migrate,
        'backup': _cmd_ledger_backup,
        'doctor': _cmd_ledger_doctor,
        'record-feedback': _cmd_ledger_record_feedback,
        'query': _cmd_ledger_query_entrypoints,
    }


def _build_memory_subparser(sub: argparse._SubParsersAction) -> dict[str, Callable]:
    memory_parser = sub.add_parser('memory')
    memory_sub = memory_parser.add_subparsers(dest='command', required=True)

    search_cmd = memory_sub.add_parser('search')
    _add_path_argument(search_cmd)
    _add_json_argument(search_cmd)
    search_cmd.add_argument('--project-id', required=True)
    search_cmd.add_argument('--run-id', required=True)
    search_cmd.add_argument('--task-id', default=None)
    search_cmd.add_argument('--agent-session-id', default=None)
    search_cmd.add_argument('--query', required=True)
    search_cmd.add_argument('--limit', type=int, default=10)

    show_cmd = memory_sub.add_parser('show')
    _add_path_argument(show_cmd)
    _add_json_argument(show_cmd)
    show_cmd.add_argument('--memory-id', required=True)

    validate_cmd = memory_sub.add_parser('validate')
    _add_path_argument(validate_cmd)
    validate_cmd.add_argument('--memory-id', required=True)
    validate_cmd.add_argument('--evidence-id', required=True)
    validate_cmd.add_argument('--validating-session-id', default=None)

    activate_cmd = memory_sub.add_parser('activate')
    _add_path_argument(activate_cmd)
    activate_cmd.add_argument('--memory-id', required=True)

    reject_cmd = memory_sub.add_parser('reject')
    _add_path_argument(reject_cmd)
    reject_cmd.add_argument('--memory-id', required=True)

    supersede_cmd = memory_sub.add_parser('supersede')
    _add_path_argument(supersede_cmd)
    supersede_cmd.add_argument('--old-memory-id', required=True)
    supersede_cmd.add_argument('--new-memory-id', required=True)
    supersede_cmd.add_argument('--project-id', required=True)
    supersede_cmd.add_argument('--memory-kind', required=True)
    supersede_cmd.add_argument('--title', required=True)
    supersede_cmd.add_argument('--content', required=True)
    supersede_cmd.add_argument('--confidence', default=None)

    return {
        'search': _cmd_memory_search,
        'show': _cmd_memory_show,
        'validate': _cmd_memory_validate,
        'activate': _cmd_memory_activate,
        'reject': _cmd_memory_reject,
        'supersede': _cmd_memory_supersede,
    }


def _build_context_subparser(sub: argparse._SubParsersAction) -> dict[str, Callable]:
    context_parser = sub.add_parser('context')
    context_sub = context_parser.add_subparsers(dest='command', required=True)

    build_cmd = context_sub.add_parser('build')
    _add_path_argument(build_cmd)
    _add_json_argument(build_cmd)
    build_cmd.add_argument('--project-id', required=True)
    build_cmd.add_argument('--user-session-id', required=True)
    build_cmd.add_argument('--run-id', required=True)
    build_cmd.add_argument('--task-id', required=True)
    build_cmd.add_argument('--budget-tokens', type=int, required=True)
    build_cmd.add_argument('--query', default=None)

    return {'build': _cmd_context_build}


def _build_parser() -> tuple[argparse.ArgumentParser, dict[str, dict[str, Callable]]]:
    parser = argparse.ArgumentParser(prog='agentmaster')
    sub = parser.add_subparsers(dest='group', required=True)
    groups = {
        'ledger': _build_ledger_subparser(sub),
        'memory': _build_memory_subparser(sub),
        'context': _build_context_subparser(sub),
    }
    return parser, groups


def main(argv: list[str] | None = None) -> int:
    parser, groups = _build_parser()
    args = parser.parse_args(argv)
    return groups[args.group][args.command](args)


if __name__ == '__main__':
    sys.exit(main())
