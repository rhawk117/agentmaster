from dataclasses import dataclass

_DIMENSION_CHECKS: tuple[tuple[str, str, str], ...] = (
    ('tokens', 'tokens_used', 'token_budget'),
    ('cost', 'cost_micro_usd_used', 'cost_micro_usd_budget'),
    ('duration', 'duration_ms_used', 'duration_ms_budget'),
    ('parallelism', 'concurrent_tasks', 'parallelism_budget'),
    ('context_pack_tokens', 'context_pack_tokens_used', 'context_pack_token_budget'),
)


@dataclass(frozen=True, slots=True)
class Budget:
    token_budget: int
    cost_micro_usd_budget: int
    duration_ms_budget: int
    parallelism_budget: int
    context_pack_token_budget: int


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    tokens_used: int
    cost_micro_usd_used: int
    duration_ms_used: int
    concurrent_tasks: int
    context_pack_tokens_used: int


@dataclass(frozen=True, slots=True)
class BudgetCheckResult:
    exceeded: bool
    exceeded_dimensions: tuple[str, ...]
    reason: str | None


def check_budget(budget: Budget, usage: BudgetUsage) -> BudgetCheckResult:
    exceeded_dimensions = tuple(
        name
        for name, usage_attr, budget_attr in _DIMENSION_CHECKS
        if getattr(usage, usage_attr) > getattr(budget, budget_attr)
    )
    if not exceeded_dimensions:
        return BudgetCheckResult(exceeded=False, exceeded_dimensions=(), reason=None)
    return BudgetCheckResult(
        exceeded=True,
        exceeded_dimensions=exceeded_dimensions,
        reason=f'budget exceeded: {", ".join(exceeded_dimensions)}',
    )


def bounded_context_pack_tokens(budget: Budget, *, requested_tokens: int) -> int:
    return min(requested_tokens, budget.context_pack_token_budget)
