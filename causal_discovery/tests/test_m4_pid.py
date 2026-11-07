import numpy as np

from causal_discovery.m4_pid import Encoder, demo_arrays, lagged_mmi_pid, mmi_pid


def test_exact_xor_one_bit_and_sum_identity():
    a = np.tile([0, 0, 1, 1], 100); b = np.tile([0, 1, 0, 1], 100); z = a ^ b
    result = mmi_pid(a, b, z)
    assert abs(result['synergy'] - 1) < 1e-12
    assert result['redundancy'] == 0 and result['unique'] == {'X1': 0.0, 'X2': 0.0}
    assert abs(result['redundancy'] + sum(result['unique'].values()) + result['synergy'] - result['joint_information']) < 1e-12
    assert result['calibration']['p_value'] is None and result['status'] == 'decomposed'


def test_exact_redundancy_unique_independent_and_conditioning():
    a = np.tile([0, 0, 1, 1], 100); b = np.tile([0, 1, 0, 1], 100)
    repeated = mmi_pid(a, a, a)
    assert repeated['redundancy'] == 1 and repeated['synergy'] == 0
    unique = mmi_pid(a, b, a)
    assert unique['unique'] == {'X1': 1.0, 'X2': 0.0} and unique['synergy'] == 0
    independent = mmi_pid(np.tile(a, 2), np.tile(b, 2), np.repeat([0, 1], len(a)))
    assert abs(independent['joint_information']) < 1e-12
    conditioned = mmi_pid(a, a, a, a)
    assert conditioned['joint_information'] == 0  # shared target memory is conditioned out.


def test_raw_nominal_categories_and_training_only_quantiles():
    result = mmi_pid(['low', 'low', 'high', 'high'], ['a', 'b', 'a', 'b'], ['no', 'yes', 'yes', 'no'])
    assert result['synergy'] == 1
    encoder = Encoder(np.linspace(0, 1, 100)[:, None].astype(object), False, 4, 8)
    before = repr(encoder.columns)
    encoded, _ = encoder.transform(np.array([[-1000], [1000]], dtype=object))
    assert encoded.tolist() == [[0], [3]] and repr(encoder.columns) == before


def test_lagged_xor_has_actual_heldout_joint_and_synergy_support():
    result = lagged_mmi_pid(**demo_arrays(seed=819))
    assert result['status'] == 'supported'
    assert result['synergy'] > .85 and result['redundancy'] < .1
    assert result['tests']['joint']['gain_bits'] > .8
    assert result['tests']['synergy']['status'] == 'supported'
    assert result['tests']['joint']['calibration']['p_value_valid']
    assert result['estimator']['bin_fit_partition'] == 'train only'
    assert not result['higher_order_synergy_evaluated']


def test_independent_dynamic_sources_not_accepted_and_sparse_tables_inconclusive():
    rng = np.random.default_rng(513)
    sources = rng.integers(0, 2, size=(3, 4000))
    result = lagged_mmi_pid(*sources, source_lags={'X1': 1, 'X2': 2})
    assert result['status'] != 'supported'
    sparse = lagged_mmi_pid(**demo_arrays(length=1200), config={'pid': {'min_training_cell_count': 10000}})
    assert sparse['status'] == 'inconclusive' and not sparse['tests']


def test_too_short_dynamic_array_does_not_invent_p_value():
    result = lagged_mmi_pid([0, 0, 1, 1], [0, 1, 0, 1], [0, 1, 1, 0], {'X1': 1, 'X2': 1})
    assert result['status'] == 'inconclusive' and result['reason'] == 'insufficient_data'
    assert not result['tests']


def test_dynamic_redundant_and_single_effective_source_have_correct_evidence():
    rng = np.random.default_rng(472); a = rng.integers(0, 2, 4000); b = rng.integers(0, 2, 4000)
    y = np.r_[0, a[:-1]]
    redundant = lagged_mmi_pid(a, a, y, {'X1': 1, 'X2': 1})
    assert redundant['redundancy'] > .95 and redundant['synergy'] < 1e-10
    assert redundant['tests']['marginal_1']['status'] == redundant['tests']['marginal_2']['status'] == 'supported'
    assert redundant['tests']['synergy']['status'] == 'rejected'
    unique = lagged_mmi_pid(a, b, y, {'X1': 1, 'X2': 1})
    assert unique['unique']['X1'] > .9 and unique['synergy'] < .1
    assert unique['tests']['marginal_1']['status'] == 'supported'
    assert unique['tests']['marginal_2']['status'] != 'supported'
