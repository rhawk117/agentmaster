"""Deterministic risk routing and scout policy (SPEC.md §9, §23 Microtask 20).

Routing is a pure function of `RiskFactors` plus an `ambiguous` flag — no
model call decides where a task goes. SPEC.md §23 MT20: "Route high-risk or
ambiguous questions to coordinator-owned scouts or stronger review; route
routine bounded implementation to the configured implementer." Risk takes
priority over ambiguity: a task that is both risky and ambiguous still needs
stronger review, not merely fact-finding.

`ImplementerScoutPolicy`/`authorize_implementer_scout` cover a distinct
concept: an *implementer*, not the coordinator, wanting to spawn its own
scout sub-agent mid-task. SPEC.md §23 MT20/§26: "Keep implementer scout
spawning disabled by default. If experimental enable is present, cap it to
one read-only scout with a separate budget and report."
"""

from dataclasses import dataclass

# SPEC.md §23 Microtask 20's exact risk factor list.
RISK_FACTOR_NAMES: tuple[str, ...] = (
    'destructive_state',
    'migration',
    'auth',
    'concurrency',
    'release',
    'schema',
    'public_api',
    'large_change_surface',
)


@dataclass(frozen=True, slots=True)
class RiskFactors:
    """Deterministic risk factors for one task (SPEC.md §23 MT20)."""

    destructive_state: bool = False
    migration: bool = False
    auth: bool = False
    concurrency: bool = False
    release: bool = False
    schema: bool = False
    public_api: bool = False
    large_change_surface: bool = False


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Where a task should be routed, and why (SPEC.md §9: "route by risk...")."""

    route: str
    risk_level: str
    risk_factors: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ImplementerScoutPolicy:
    """Whether an implementer may spawn its own read-only scout sub-agent.

    Disabled by default (SPEC.md §26: "Implementer scout spawning is disabled
    by default"); enabling is an explicit, experimental opt-in.
    """

    enabled: bool = False
    scout_budget_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ScoutAuthorization:
    """The result of one `authorize_implementer_scout` call."""

    authorized: bool
    max_scouts: int
    read_only: bool
    budget_tokens: int
    reason: str


def active_risk_factors(factors: RiskFactors) -> tuple[str, ...]:
    """Return the subset of `RISK_FACTOR_NAMES` set on `factors`, in order."""
    return tuple(name for name in RISK_FACTOR_NAMES if getattr(factors, name))


def classify_risk(factors: RiskFactors) -> str:
    """Return `'high'` if any risk factor is set, else `'routine'`."""
    return 'high' if active_risk_factors(factors) else 'routine'


def route_task(factors: RiskFactors, *, ambiguous: bool = False) -> RoutingDecision:
    """Route one task by its risk factors and ambiguity.

    A set risk factor always routes to `'stronger_review'`, even when the
    task is also ambiguous. An ambiguous but otherwise routine task routes to
    a coordinator-owned scout for fact-finding. Everything else routes to the
    configured implementer.
    """
    risk_factors = active_risk_factors(factors)
    if risk_factors:
        return RoutingDecision(
            route='stronger_review',
            risk_level='high',
            risk_factors=risk_factors,
            reason=f'risk factors present: {", ".join(risk_factors)}',
        )
    if ambiguous:
        return RoutingDecision(
            route='coordinator_scout',
            risk_level='high',
            risk_factors=(),
            reason='ambiguous with no set risk factors',
        )
    return RoutingDecision(
        route='implementer',
        risk_level='routine',
        risk_factors=(),
        reason='routine bounded implementation',
    )


def authorize_implementer_scout(
    policy: ImplementerScoutPolicy, requested_scouts: int
) -> ScoutAuthorization:
    """Authorize (or refuse) an implementer's request to spawn scouts.

    Refuses whenever `policy.enabled` is `False` (the default) or
    `requested_scouts` is not positive. Otherwise caps the authorization to
    exactly one read-only scout with `policy.scout_budget_tokens`, regardless
    of how many were requested.
    """
    if not policy.enabled:
        return ScoutAuthorization(
            authorized=False,
            max_scouts=0,
            read_only=True,
            budget_tokens=0,
            reason='implementer scout spawning is disabled by default',
        )
    if requested_scouts < 1:
        return ScoutAuthorization(
            authorized=False,
            max_scouts=0,
            read_only=True,
            budget_tokens=0,
            reason='no scout requested',
        )
    return ScoutAuthorization(
        authorized=True,
        max_scouts=1,
        read_only=True,
        budget_tokens=policy.scout_budget_tokens,
        reason='capped to one read-only scout with a separate budget',
    )
