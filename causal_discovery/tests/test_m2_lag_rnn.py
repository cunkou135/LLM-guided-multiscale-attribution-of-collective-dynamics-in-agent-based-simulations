import numpy as np
import torch

from causal_discovery.m2_lag_rnn import estimate_lags


def known(seed, n=512, correlated=False):
    rng = np.random.default_rng(seed); x = rng.normal(size=n + 200); y = np.zeros(n + 200)
    if correlated:
        for t in range(1, len(x)): x[t] = .85 * x[t - 1] + .5 * x[t]
    for t in range(3, len(y)): y[t] = .55 * y[t - 2] + 1.5 * np.sin(x[t - 3]) + .12 * rng.normal()
    return x[200:], y[200:]


def test_known_external_and_self_lags_from_independent_runs_and_step_units(tmp_path):
    data = {f'r{i}': known(2024 + i, n=300) for i in range(8)}
    x = {k: v[0] for k, v in data.items()}; y = {k: v[1] for k, v in data.items()}
    result = estimate_lags(y, {'X': x}, steps={k: np.arange(300) * 3 for k in data}, artifact_dir=tmp_path)
    assert result['status'] in ('estimated', 'unstable')
    assert abs(result['primary_lags']['X'] - 9) <= 3
    assert 6 in result['self_memory_lags']
    assert result['split']['mode'] == 'independent_runs'
    assert result['test_partition_used'] is False
    assert any(e['lag'] == 6 and e['status'] == 'supported' for e in result['self_evidence'])
    for model in result['models']:
        checkpoint = torch.load(model['parameter_file'], weights_only=True)
        assert checkpoint['state_dict'] and model['history'] and model['best_epoch'] > 0


def test_short_arrays_report_insufficient_data_without_training():
    result = estimate_lags([1, 2, 4, 3], {'X': [3, 1, 2, 5]})
    assert result['status'] == 'insufficient_data' and not result['models']


def test_iid_has_no_confirmed_self_history():
    rng = np.random.default_rng(3901)
    result = estimate_lags(rng.normal(size=2400), {'X': rng.normal(size=2400)},
                           config={'rnn': {'epochs': 80, 'min_epochs': 25, 'patience': 15}})
    assert not any(e['status'] == 'supported' for e in result['self_evidence'])
    assert all(n['status'] in ('estimated', 'unstable', 'not_supported') for n in result['lag_evidence'].values())


def test_correlated_adjacent_lags_report_actual_seed_stability():
    x, y = known(909, 2400, correlated=True)
    result = estimate_lags(y, {'X': x}, config={'rnn': {'epochs': 100}})
    assert result['primary_lags']['X'] is not None and abs(result['primary_lags']['X'] - 3) <= 1
    evidence = result['lag_evidence']['X']
    assert len(evidence['validation_gain_by_seed']) == 2
    assert len(evidence['seed_support_fraction']) == 4
    assert evidence['status'] in ('estimated', 'unstable')
    assert all(lag in [1, 2, 3, 4] for lag in result['parent_lags']['X'])
