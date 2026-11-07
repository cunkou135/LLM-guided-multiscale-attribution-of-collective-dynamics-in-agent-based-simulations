import numpy as np

from causal_discovery.m3_granger import demo_arrays, test_granger as granger
from causal_discovery._common import calibrate_gain


def test_actual_nonlinear_forward_reverse_and_matched_capacity(tmp_path):
    arrays = demo_arrays(seed=1701)
    result = granger(**arrays, artifact_dir=tmp_path)
    assert result['status'] == 'supported' and result['prediction_gain'] > .2
    assert abs(result['primary_lag'] - 2) <= 1
    assert result['calibration']['p_value_valid'] and result['calibration']['p_value'] <= .05
    assert not result['test_partition_used_for_lag_selection']
    for models in result['models']:
        assert models['restricted']['parameter_count'] == models['full']['parameter_count']
        assert models['restricted']['max_epochs'] == models['full']['max_epochs']
    reverse = granger(arrays['y'], arrays['x'], [1, 2, 3, 4])
    assert reverse['status'] != 'supported' and reverse['prediction_gain'] < result['prediction_gain']


def test_independent_source_is_not_accepted():
    result = granger(**demo_arrays(seed=411, independent=True))
    assert result['status'] in ('rejected', 'inconclusive')
    assert result['prediction_gain'] < .05


def test_short_arrays_and_missing_calibration_are_inconclusive():
    assert granger([1, 2, 3], [3, 2, 1], [1])['status'] == 'inconclusive'
    result = calibrate_gain({'r': np.ones(100)}, {'calibration': {'assume_weak_stationarity': False}})
    assert result['p_value'] is None and not result['p_value_valid']
    result = calibrate_gain({'r': np.linspace(0, 10, 500)})
    assert result['p_value'] is None and 'diagnostic' in result['reason']


def test_block_calibration_positive_and_null_score_differences():
    rng = np.random.default_rng(800)
    supported = calibrate_gain({'r': .4 + rng.normal(size=1000)})
    assert supported['p_value_valid'] and supported['p_value'] <= .05
    # A predeclared small Monte Carlo check; this tests the calibrator, not an NN fixture.
    pvalues = []
    for i in range(20):
        noise = np.random.default_rng(100 + i).normal(size=800)
        for t in range(1, len(noise)): noise[t] += .3 * noise[t - 1]
        result = calibrate_gain({'r': noise}, {'calibration': {'bootstrap_repeats': 199, 'block_length': 12}}, seed=i)
        if result['p_value_valid']: pvalues.append(result['p_value'])
    assert len(pvalues) >= 18 and sum(p <= .05 for p in pvalues) <= 4
