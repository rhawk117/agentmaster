"""Per-run/per-task budget enforcement (SPEC.md §9, §23 Microtask 20).

SPEC.md §23 MT20: "Enforce per-run/per-task token, cost, duration,
parallelism, and context-pack budgets without silently changing acceptance
criteria." `check_budget` only reports which dimensions were exceeded, so a
caller that stops dispatch on `exceeded=True` never touches
`TASK.acceptance_json` — the hard-budget stop is a dispatch decision, not a
scope change. `bounded_context_pack_tokens` is the seam a context-pack caller
uses to cap `ledger.context_pack.ContextPackRequest.budget_tokens` at the
run's hard `context_pack_token_budget` before building a pack.
"""

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
    """A run or task's hard resource ceilings (SPEC.md §9.4 MT20)."""

    token_budget: int
    cost_micro_usd_budget: int
    duration_ms_budget: int
    parallelism_budget: int
    context_pack_token_budget: int


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    """Resource consumption to compare against a `Budget`."""

    tokens_used: int
    cost_micro_usd_used: int
    duration_ms_used: int
    concurrent_tasks: int
    context_pack_tokens_used: int


@dataclass(frozen=True, slots=True)
class BudgetCheckResult:
    """The outcome of one `check_budget` call."""

    exceeded: bool
    exceeded_dimensions: tuple[str, ...]
    reason: str | None


def check_budget(budget: Budget, usage: BudgetUsage) -> BudgetCheckResult:
    """Compare `usage` against `budget` on every dimension.

    Returns
    -------
    BudgetCheckResult
        `exceeded_dimensions` lists every dimension where usage strictly
        exceeds its ceiling, in `_DIMENSION_CHECKS` order. Empty means every
        dimension is within budget.
    """
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
    """Cap a requested context-pack token budget at `budget.context_pack_token_budget`."""
    return min(requested_tokens, budget.context_pack_token_budget)
