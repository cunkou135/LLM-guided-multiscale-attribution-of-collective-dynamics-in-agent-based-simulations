from copy import deepcopy

import pytest

from causal_discovery.m5_graph import adjust_pvalues, demo_payload, integrate_graph, validate_final_graph


def test_joint_only_complete_ids_lags_feedback_and_removed_node():
    payload = demo_payload(); original = deepcopy(payload['graph'])
    result = integrate_graph(**payload)
    graph = result['graph']; validate_final_graph(graph)
    assert payload['graph'] == original
    assert {n['node_id'] for n in graph['nodes']} == {'A', 'B', 'Y', 'T'}
    edges = {(e['source'], e['target']): e for e in graph['edges']}
    assert edges[('A', 'Y')]['edge_id'] == 'e0' and edges[('B', 'Y')]['edge_id'] == 'e1'
    assert edges[('A', 'Y')]['relation_type'] == edges[('B', 'Y')]['relation_type'] == 'joint_only'
    assert edges[('A', 'Y')]['joint_group_id'] == edges[('B', 'Y')]['joint_group_id']
    assert edges[('A', 'Y')]['weight'] == 2 and edges[('B', 'Y')]['weight'] == 3
    assert edges[('A', 'T')]['weight'] == 2 and edges[('T', 'A')]['weight'] == 1
    assert edges[('T', 'T')]['relation_type'] == 'self_memory' and edges[('T', 'T')]['weight'] == 1
    assert 'bad' in result['audit']['removed_nodes']
    assert not any(e['source'] == 'bad' or e['target'] == 'bad' for e in graph['edges'])
    assert all(n['mathematical_definition'] == next(v['mathematical_definition'] for v in original['nodes'] if v['node_id'] == n['node_id']) for n in graph['nodes'])


def test_missing_joint_member_does_not_leave_partial_relation():
    payload = demo_payload(); payload['data']['valid_nodes'].remove('B')
    payload['data']['invalid_nodes']['B'] = {'reason': 'required source missing'}
    result = integrate_graph(**payload)
    assert not any(e['target'] == 'Y' for e in result['graph']['edges'])
    assert 'Y' in result['audit']['valid_isolated_nodes']
    invalid = integrate_graph(**demo_payload())['graph']
    invalid['edges'] = [e for e in invalid['edges'] if not (e['source'] == 'B' and e['target'] == 'Y')]
    with pytest.raises(ValueError, match='Incomplete joint'): validate_final_graph(invalid)


def test_individual_and_joint_evidence_share_one_original_edge():
    payload = demo_payload(); record = payload['pid_results'][0]
    record['tests']['marginal_1'] = {'gain_bits': .2, 'status': 'supported', 'calibration': {'p_value': .001, 'p_value_valid': True}}
    record['i1'] = .2
    result = integrate_graph(**payload)['graph']
    selected = [e for e in result['edges'] if e['source'] == 'A' and e['target'] == 'Y']
    assert len(selected) == 1 and selected[0]['relation_type'] == 'individual_predictive'
    assert {e['kind'] for e in selected[0]['evidence']} == {'pid_marginal', 'pid_joint'}


def test_zero_mmi_unique_does_not_remove_redundant_sources():
    payload = demo_payload(); record = payload['pid_results'][0]
    record.update(synergy=0, redundancy=1, unique={'A': 0, 'B': 0})
    for name in ('marginal_1', 'marginal_2'):
        record['tests'][name] = {'gain_bits': .9, 'status': 'supported', 'calibration': {'p_value': .001, 'p_value_valid': True}}
    record['tests']['synergy']['status'] = 'rejected'
    edges = [e for e in integrate_graph(**payload)['graph']['edges'] if e['target'] == 'Y']
    assert len(edges) == 2 and all(e['relation_type'] == 'individual_predictive' for e in edges)
    assert not any(v['kind'] == 'pid_joint' for e in edges for v in e['evidence'])


def test_only_actual_p_values_are_corrected_and_missing_support_never_accepted():
    correction = adjust_pvalues({'good': {'p_value': .001, 'p_value_valid': True}, 'none': {'p_value': None},
                                 'bad': {'p_value': float('nan'), 'p_value_valid': True}, 'boolean': {'p_value': False, 'p_value_valid': True}})
    assert correction['tested_count'] == 1 and set(correction['excluded']) == {'none', 'bad', 'boolean'}
    payload = demo_payload()
    for record in payload['granger_results']:
        record.update(status='inconclusive', prediction_gain=None, calibration={'p_value': None, 'p_value_valid': False}, reason='insufficient samples')
    result = integrate_graph(**payload)
    assert not any(e['method'] == 'rnn_granger' for e in result['graph']['edges'])
    assert any(r.get('upstream_reason') == 'insufficient samples' for r in result['audit']['decisions'])


def test_scalar_pid_lag_format_and_simplified_m2_status_are_supported():
    payload = demo_payload()
    payload['pid_results'][0]['source_lags'] = {'A': 2, 'B': 3}
    for r in payload['lag_results']:
        r.pop('parent_status'); r['status'] = 'estimated'
    result = integrate_graph(**payload)
    assert len([e for e in result['graph']['edges'] if e['relation_type'] == 'joint_only']) == 2


def test_no_test_result_keeps_valid_isolated_nodes_and_records_every_candidate():
    payload = demo_payload(); payload.update(lag_results=[], granger_results=[], pid_results=[])
    result = integrate_graph(**payload)
    assert len(result['graph']['nodes']) == 4 and result['graph']['edges'] == []
    assert len(result['audit']['candidate_edge_decisions']) == len(payload['graph']['edges'])


def test_schema_rejects_wrong_lag_weight_and_dangling_edges():
    graph = integrate_graph(**demo_payload())['graph']; graph['edges'][0]['weight'] = 0
    with pytest.raises(Exception): validate_final_graph(graph)
    graph = integrate_graph(**demo_payload())['graph']; graph['edges'][0]['source'] = 'absent'
    with pytest.raises(ValueError, match='Dangling'): validate_final_graph(graph)
