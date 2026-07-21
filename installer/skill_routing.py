"""Deterministic routing of the writing-skills capability onto plan tasks.

Section 20.1: a task earns the writing-skills checklist only when it both
declares the capability via `Uses:` AND its scope materially touches a
SKILL.md, agent definition, frontmatter block, or other skill-authoring
target. Either condition without the other is a plan defect worth surfacing,
never a silent auto-route.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from installer.capabilities import CAPABILITIES

if TYPE_CHECKING:
    from installer.plan_parser import PlanTask


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """The routing outcome for one task and one capability."""

    task_id: str
    capability: str
    requested: bool
    triggered: bool
    routed: bool
    mismatch: bool
    reason: str


def _scope_triggers(scope: str, capability: str) -> bool:
    haystack = scope.lower()
    return any(
        keyword in haystack for keyword in CAPABILITIES[capability].trigger_keywords
    )


def route(task: PlanTask, capability: str = 'writing-skills') -> RoutingDecision:
    """Decide whether `task` should receive `capability`'s checklist.

    Parameters
    ----------
    task : PlanTask
        A parsed plan task, as returned by `installer.plan_parser.parse_tasks`.
    capability : str
        The registered capability name to route (default `writing-skills`).

    Returns
    -------
    RoutingDecision
        `routed` is true only when the task both declares the capability and
        its scope matches the capability's trigger boundary.
    """
    requested = capability in task.uses
    triggered = _scope_triggers(task.scope, capability)
    routed = requested and triggered
    mismatch = requested != triggered

    if not mismatch:
        reason = (
            f'{task.task_id}: scope matches {capability} trigger boundary'
            if routed
            else f'{task.task_id}: {capability} not requested and scope does not trigger'
        )
    elif requested and not triggered:
        reason = (
            f'{task.task_id}: Uses: {capability} declared but scope "{task.scope}" '
            f'does not create or materially change skill/agent definitions'
        )
    else:
        reason = (
            f'{task.task_id}: scope "{task.scope}" touches skill/agent definitions '
            f'but Uses: {capability} was not declared'
        )

    return RoutingDecision(
        task_id=task.task_id,
        capability=capability,
        requested=requested,
        triggered=triggered,
        routed=routed,
        mismatch=mismatch,
        reason=reason,
    )
