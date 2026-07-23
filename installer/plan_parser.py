import re
from dataclasses import dataclass

from installer.capabilities import CAPABILITIES

_TASK_HEADER = re.compile(
    r'^\*\*(?P<task_id>T\d+[a-z]?)\s*—\s*(?P<title>.+?)\*\*', re.MULTILINE
)
_SCOPE_LINE = re.compile(r'^Scope:\s*(?P<value>.+)$', re.MULTILINE)
_USES_LINE = re.compile(r'^Uses:\s*(?P<value>.+)$', re.MULTILINE)

_REPO_SKILL_NAMES = frozenset({
    'agentmaster-plan',
    'agentmaster-execute',
    'agentmaster-review',
    'agentmaster-retro',
})


@dataclass(frozen=True, slots=True)
class PlanTask:
    task_id: str
    title: str
    uses: tuple[str, ...]
    scope: str
    body: str


class UnknownCapabilityError(ValueError):
    def __init__(self, *, task_id: str, capability: str) -> None:
        self.task_id = task_id
        self.capability = capability
        super().__init__(
            f'{task_id}: unknown capability "{capability}" in Uses: line — '
            'not a registered capability, repo skill, or namespaced reference'
        )


def parse_tasks(plan_text: str) -> list[PlanTask]:
    headers = list(_TASK_HEADER.finditer(plan_text))
    tasks: list[PlanTask] = []
    for index, match in enumerate(headers):
        start = match.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(plan_text)
        body = plan_text[start:end]

        scope_match = _SCOPE_LINE.search(body)
        scope = scope_match.group('value').strip() if scope_match else ''

        uses_match = _USES_LINE.search(body)
        uses_value = uses_match.group('value').strip() if uses_match else 'none'
        uses = tuple(token.strip() for token in uses_value.split(',') if token.strip())

        tasks.append(
            PlanTask(
                task_id=match.group('task_id'),
                title=match.group('title'),
                uses=uses,
                scope=scope,
                body=body,
            )
        )
    return tasks


def _is_known(token: str) -> bool:
    if token == 'none' or ':' in token:
        return True
    return token in CAPABILITIES or token in _REPO_SKILL_NAMES


def validate_uses(tasks: list[PlanTask]) -> list[str]:
    return [
        str(UnknownCapabilityError(task_id=task.task_id, capability=token))
        for task in tasks
        for token in task.uses
        if not _is_known(token)
    ]
