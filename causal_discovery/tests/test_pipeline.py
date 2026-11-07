import ast
from pathlib import Path

import numpy as np
import pytest

from causal_discovery._common import read_json, settings, sha256
from causal_discovery.m1_data import align_target
from causal_discovery.m2_lag_rnn import estimate_lags
from causal_discovery.m3_granger import test_granger as granger
from causal_discovery.m4_pid import lagged_mmi_pid
from causal_discovery.m5_graph import integrate_graph, validate_final_graph
from causal_discovery.pipeline import make_demo_graph, pid_pair_plan, run_pipeline


def test_disjoint_target_coordinates_are_inconclusive_not_a_pipeline_crash(tmp_path):
    graph = make_demo_graph()
    graph['nodes'] = [n for n in graph['nodes'] if n['node_id'] in ('X', 'Y')]
    graph['edges'] = [e for e in graph['edges'] if e['source'] in ('X', 'Y') and e['target'] in ('X', 'Y')]
    for item in graph['demo_series']['Y'].values():
        item['steps'] = [t + 10000 for t in item['steps']]
    result = run_pipeline(graph, tmp_path / 'final.json')
    assert len(result['graph']['nodes']) == 2 and result['graph']['edges'] == []
    audit = Path(result['report']['audit_directory'])
    records = read_json(audit / 'm3_granger_results.json')
    assert len(records) == 2 and all(r['status'] == 'inconclusive' and 'no common' in r['reason'] for r in records)


@pytest.fixture(scope='module')
def completed(tmp_path_factory):
    directory = tmp_path_factory.mktemp('discovery_pipeline')
    graph = make_demo_graph()
    result = run_pipeline(graph, directory / 'final_causal_graph.json')
    return graph, result, directory


def test_demo_real_algorithms_expected_controls_and_lag_weights(completed):
    source, result, directory = completed
    graph = result['graph']; validate_final_graph(graph)
    assert {n['node_id'] for n in graph['nodes']} == {'X', 'A', 'B', 'Y', 'Z', 'W'}
    edges = {(e['source'], e['target']): e for e in graph['edges']}
    assert ('X', 'Y') in edges and ('Y', 'X') not in edges
    assert edges[('X', 'Y')]['weight'] == 2
    assert edges[('Y', 'Y')]['weight'] == 1
    assert edges[('A', 'Z')]['weight'] == 2 and edges[('B', 'Z')]['weight'] == 3
    assert edges[('A', 'Z')]['relation_type'] == edges[('B', 'Z')]['relation_type'] == 'joint_only'
    assert edges[('A', 'Z')]['joint_group_id'] == edges[('B', 'Z')]['joint_group_id']
    assert all(e['source'] != 'bad' and e['target'] != 'bad' for e in graph['edges'])
    assert not any(e['source'] == 'W' or e['target'] == 'W' for e in graph['edges'])
    assert source['nodes'][-1]['node_id'] == 'bad'  # source not edited by adaptation.
    assert result['report']['new_llm_calls'] == 0


def test_standalone_and_integrated_actual_computations_agree(completed):
    _, result, directory = completed
    audit = Path(result['report']['audit_directory'])
    data, cfg = read_json(audit / 'm1_data.json'), settings()
    records = {r['target']: r for r in read_json(audit / 'm2_lag_results.json')}
    for target, parents in [('Y', ['X']), ('Z', ['A', 'B'])]:
        aligned = align_target(data, target, parents)
        independent = estimate_lags(aligned['y'], aligned['parents'], steps=aligned['steps'], target=target, config=cfg,
                                    artifact_dir=directory / 'independent' / target)
        assert independent['parent_lags'] == records[target]['parent_lags']
        assert independent['primary_lags'] == records[target]['primary_lags']
        assert independent['self_memory_lags'] == records[target]['self_memory_lags']
    aligned = align_target(data, 'Y', ['X']); lag = records['Y']
    independent_g = granger(aligned['parents']['X'], aligned['y'], lag['parent_lags']['X'], primary_lag=lag['primary_lags']['X'],
                            steps=aligned['steps'], source='X', target='Y', artifact_dir=directory / 'independent_granger')
    integrated_g = next(r for r in read_json(audit / 'm3_granger_results.json') if r['target'] == 'Y')
    assert independent_g['status'] == integrated_g['status']
    assert np.isclose(independent_g['prediction_gain'], integrated_g['prediction_gain'], atol=1e-7)
    aligned = align_target(data, 'Z', ['A', 'B']); lag = records['Z']
    independent_pid = lagged_mmi_pid(aligned['parents']['A'], aligned['parents']['B'], aligned['y'], lag['parent_lags'],
                                     primary_lags=lag['primary_lags'], sources=('A', 'B'), target='Z', steps=aligned['steps'])
    integrated_pid = read_json(audit / 'm4_pid_results.json')[0]
    assert independent_pid['synergy'] == integrated_pid['synergy']
    assert independent_pid['tests'] == integrated_pid['tests']


def test_target_routing_and_complete_m5_replay(completed):
    source, result, _ = completed; audit = Path(result['report']['audit_directory'])
    routes = {r['target']: r for r in read_json(audit / 'routing.json')}
    assert routes['Y']['external_parent_count'] == 1 and routes['Y']['method'] == 'm3_granger'
    assert routes['Z']['external_parent_count'] == 2 and routes['Z']['method'] == 'm4_pid'
    assert routes['W']['method'] == 'self_history_only'
    replay = integrate_graph(source, read_json(audit / 'm1_data.json'), read_json(audit / 'm2_lag_results.json'),
                             read_json(audit / 'm3_granger_results.json'), read_json(audit / 'm4_pid_results.json'))['graph']
    assert replay['nodes'] == result['graph']['nodes'] and replay['edges'] == result['graph']['edges']


def test_every_module_has_independent_main_without_cross_m_imports():
    folder = Path('causal_discovery')
    for name in ('m1_data', 'm2_lag_rnn', 'm3_granger', 'm4_pid', 'm5_graph'):
        tree = ast.parse((folder / (name + '.py')).read_text(encoding='utf-8'))
        assert any(isinstance(n, ast.FunctionDef) and n.name == 'main' for n in tree.body)
        assert not any(isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(('m1_', 'm2_', 'm3_', 'm4_', 'm5_')) for n in ast.walk(tree))


def test_pair_strategy_is_bounded_and_empty_real_graph_stays_empty(tmp_path):
    from itertools import combinations
    nodes = ['A', 'B', 'C', 'D', 'E']
    plan = pid_pair_plan(nodes, 3)
    assert len(plan['evaluated_pairs']) == 3 and len(plan['omitted_pairs']) == 7
    assert set(map(tuple, plan['evaluated_pairs'] + plan['omitted_pairs'])) == set(combinations(nodes, 2))
    assert plan == pid_pair_plan(nodes[::-1], 3)
    assert not plan['higher_order_synergy_evaluated']
    graph = {'nodes': [], 'edges': [], 'run_ids': ['r']}
    result = run_pipeline(graph, tmp_path / 'final_causal_graph.json')
    assert result['graph']['nodes'] == [] and result['graph']['edges'] == []
    assert result['report']['reason'] == 'empty_input_graph'


def test_real_saved_first_part_inputs_are_admitted_honestly(tmp_path):
    cfg = {'data': {'node_overrides': {
        'frag_micro_nn_distance': {'entity_mode': 'aggregate', 'aggregation': 'mean'},
        'elong_micro_axis_alignment': {'entity_mode': 'aggregate', 'aggregation': 'mean'},
        'icts_meso_layer_contact_change': {'features': ['c', 'h', 's', 'w']}}}}
    for scene in ('fish', 'covasim'):
        source = Path('causal_graph/results/v2_live_20261106') / scene / 'executable_graph.json'
        if not source.exists(): pytest.skip('Real local trajectory acceptance files absent')
        before = sha256(source)
        result = run_pipeline(source, tmp_path / scene / 'final_causal_graph.json', cfg)
        assert result['report']['status'] == 'no_analyzable_nodes'
        assert result['graph']['nodes'] == [] and result['graph']['edges'] == []
        assert result['report']['granger_tests'] == result['report']['pid_pairs'] == 0
        assert sha256(source) == before
        data = read_json(Path(result['report']['audit_directory']) / 'm1_data.json')
        reasons = [r['reason'] for r in data['invalid_nodes'].values()]
        assert any('insufficient' in r or 'constant' in r for r in reasons)
        if scene == 'fish':
            runs = data['invalid_nodes']['frag_micro_nn_distance']['report']['runs']
            assert all(r['transformation']['aggregation'] == 'mean' and 'formula' in r['transformation'] for r in runs.values())
