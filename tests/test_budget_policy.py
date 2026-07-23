from ledger.budget_policy import (
    Budget,
    BudgetUsage,
    bounded_context_pack_tokens,
    check_budget,
)

_BUDGET = Budget(
    token_budget=1000,
    cost_micro_usd_budget=500,
    duration_ms_budget=60_000,
    parallelism_budget=3,
    context_pack_token_budget=200,
)

_USAGE_WITHIN_BUDGET = BudgetUsage(
    tokens_used=100,
    cost_micro_usd_used=50,
    duration_ms_used=1_000,
    concurrent_tasks=1,
    context_pack_tokens_used=50,
)


def test_check_budget_passes_when_every_dimension_is_within_budget():
    result = check_budget(_BUDGET, _USAGE_WITHIN_BUDGET)

    assert result.exceeded is False
    assert result.exceeded_dimensions == ()
    assert result.reason is None


def test_check_budget_reports_the_exceeded_token_dimension():
    usage = BudgetUsage(
        tokens_used=1_001,
        cost_micro_usd_used=50,
        duration_ms_used=1_000,
        concurrent_tasks=1,
        context_pack_tokens_used=50,
    )

    result = check_budget(_BUDGET, usage)

    assert result.exceeded is True
    assert result.exceeded_dimensions == ('tokens',)
    assert result.reason is not None
    assert 'tokens' in result.reason


def test_check_budget_reports_every_exceeded_dimension():
    usage = BudgetUsage(
        tokens_used=1_001,
        cost_micro_usd_used=501,
        duration_ms_used=60_001,
        concurrent_tasks=4,
        context_pack_tokens_used=201,
    )

    result = check_budget(_BUDGET, usage)

    assert result.exceeded is True
    assert result.exceeded_dimensions == (
        'tokens',
        'cost',
        'duration',
        'parallelism',
        'context_pack_tokens',
    )


def test_check_budget_does_not_mutate_the_budget_or_usage_inputs():
    check_budget(_BUDGET, _USAGE_WITHIN_BUDGET)

    assert _BUDGET.token_budget == 1000
    assert _USAGE_WITHIN_BUDGET.tokens_used == 100


def test_bounded_context_pack_tokens_caps_a_request_at_the_hard_budget():
    assert bounded_context_pack_tokens(_BUDGET, requested_tokens=10_000) == 200


def test_bounded_context_pack_tokens_passes_through_a_request_within_budget():
    assert bounded_context_pack_tokens(_BUDGET, requested_tokens=50) == 50
