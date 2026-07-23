from ledger.risk_routing import (
    ImplementerScoutPolicy,
    RiskFactors,
    active_risk_factors,
    authorize_implementer_scout,
    classify_risk,
    route_task,
)


def test_classify_risk_is_routine_when_no_factors_are_set():
    assert classify_risk(RiskFactors()) == 'routine'


def test_classify_risk_is_high_when_any_factor_is_set():
    assert classify_risk(RiskFactors(migration=True)) == 'high'


def test_active_risk_factors_names_only_the_set_factors():
    factors = RiskFactors(auth=True, schema=True)
    assert active_risk_factors(factors) == ('auth', 'schema')


def test_route_task_sends_routine_bounded_work_to_the_implementer():
    decision = route_task(RiskFactors())

    assert decision.route == 'implementer'
    assert decision.risk_level == 'routine'
    assert decision.risk_factors == ()


def test_route_task_sends_high_risk_work_to_stronger_review():
    decision = route_task(RiskFactors(destructive_state=True))

    assert decision.route == 'stronger_review'
    assert decision.risk_level == 'high'
    assert 'destructive_state' in decision.risk_factors


def test_route_task_sends_ambiguous_routine_work_to_a_coordinator_scout():
    decision = route_task(RiskFactors(), ambiguous=True)

    assert decision.route == 'coordinator_scout'
    assert decision.risk_level == 'high'


def test_route_task_prefers_stronger_review_when_both_risky_and_ambiguous():
    decision = route_task(RiskFactors(auth=True), ambiguous=True)

    assert decision.route == 'stronger_review'


def test_implementer_scout_spawning_is_disabled_by_default():
    authorization = authorize_implementer_scout(
        ImplementerScoutPolicy(), requested_scouts=1
    )

    assert authorization.authorized is False
    assert authorization.max_scouts == 0


def test_implementer_scout_spawning_is_capped_to_one_read_only_scout_when_enabled():
    policy = ImplementerScoutPolicy(enabled=True, scout_budget_tokens=500)

    authorization = authorize_implementer_scout(policy, requested_scouts=5)

    assert authorization.authorized is True
    assert authorization.max_scouts == 1
    assert authorization.read_only is True
    assert authorization.budget_tokens == 500


def test_implementer_scout_authorization_refuses_a_zero_scout_request():
    policy = ImplementerScoutPolicy(enabled=True, scout_budget_tokens=500)

    authorization = authorize_implementer_scout(policy, requested_scouts=0)

    assert authorization.authorized is False
