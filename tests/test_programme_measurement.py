from ai_trader.programme_measurement import compare, difference


def sample(version='v', equity=100, informative=1):
    return dict(at='dated', experiments=[dict(id='one', version=version,
        broker='kraken', currency='GBP', baseline_equity=equity,
        candidate_equity=equity, informative=informative)],
        accounts=[dict(broker='alpaca', account_mode='paper', currency='USD', portfolio_value=equity)])


def test_equal_gains_do_not_establish_edge_or_account_net_profit():
    result = compare(sample(equity=120, informative=3), sample())
    assert result['experiments'][0]['candidate_equity_change'] == 20
    assert result['experiments'][0]['relative_change'] == 0
    assert result['experiments'][0]['new_informative'] == 2
    assert result['accounts'][0]['observed_equity_change'] == 20
    assert result['accounts'][0]['verified_strategy_net_profit'] is None
    assert result['profitability'] == 'not_established'


def test_changed_version_and_regressed_counts_cannot_pass():
    assert compare(sample(version='new'), sample())['experiments'][0]['status'] == 'incomparable_version_or_scope'
    assert compare(sample(informative=0), sample())['experiments'][0]['status'] == 'counter_regression_requires_investigation'


def test_missing_values_are_not_zero_and_currencies_are_not_mixed():
    for value in (None, 'NaN', 'Infinity', 'unknown'):
        assert difference(value, 1) is None
    now = sample()
    now['experiments'][0]['currency'] = 'USD'
    now['accounts'][0]['account_mode'] = 'live'
    result = compare(now, sample())
    assert 'candidate_equity_change' not in result['experiments'][0]
    assert result['accounts'][0]['observed_equity_change'] is None
