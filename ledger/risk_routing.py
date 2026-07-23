from dataclasses import dataclass

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
    route: str
    risk_level: str
    risk_factors: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ImplementerScoutPolicy:
    enabled: bool = False
    scout_budget_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ScoutAuthorization:
    authorized: bool
    max_scouts: int
    read_only: bool
    budget_tokens: int
    reason: str


def active_risk_factors(factors: RiskFactors) -> tuple[str, ...]:
    return tuple(name for name in RISK_FACTOR_NAMES if getattr(factors, name))


def classify_risk(factors: RiskFactors) -> str:
    return 'high' if active_risk_factors(factors) else 'routine'


def route_task(factors: RiskFactors, *, ambiguous: bool = False) -> RoutingDecision:
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
