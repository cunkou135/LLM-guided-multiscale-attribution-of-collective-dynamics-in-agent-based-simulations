import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from causal_discovery.m1_data import adapt_graph, align_arrays, align_target
from causal_discovery._common import make_windows, align_runs, settings, sha256


def permissive():
    return {'data': {'min_total_observations': 8, 'min_samples_per_run': 4},
            'rnn': {'max_lag': 1}, 'split': {'min_windows': dict.fromkeys(('train', 'validation', 'confirmation', 'test'), 1)}}


def graph_with_files(tmp_path):
    nodes = []
    for name in ('X', 'Y'):
        frame = pd.DataFrame({'run_id': ['a'] * 40, 'indicator_id': [name] * 40, 'step': np.arange(40),
                              'feature': ['value'] * 40, 'value': np.sin(np.arange(40) * .7 + (name == 'Y'))})
        file = tmp_path / f'{name}.parquet'; frame.to_parquet(file)
        nodes.append({'node_id': name, 'indicator_id': name, 'scale': 'macro', 'mathematical_definition': f'recorded {name}(t)',
                      'execution': {'a': {'status': 'success', 'series_file': file.name, 'series_sha256': sha256(file)}}})
    return {'run_ids': ['a'], 'nodes': nodes, 'edges': [{'edge_id': 'e', 'source': 'X', 'target': 'Y'}]}


def test_arrays_alignment_missing_gaps_and_bad_coordinates():
    result = align_arrays([1, np.nan, 3, 4], [2, 3, 4, 6], [0, 1, 2, 3])
    assert result['x'] == [[1.0], [3.0], [4.0]] and result['steps'] == [0, 2, 3]
    assert result['report']['gaps_present']
    with pytest.raises(ValueError): align_arrays([1, 2, 3], [2, 3, 4], [0, 0, 1])
    with pytest.raises(ValueError): align_arrays([1, np.inf, 3], [2, 3, 4])
    assert align_arrays([1] * 6, list(range(6)))['status'] == 'invalid'


def test_actual_parquet_hashes_valid_nodes_and_isolates(tmp_path):
    graph = graph_with_files(tmp_path)
    before = json.dumps(graph)
    result = adapt_graph(graph, permissive(), base_dir=tmp_path)
    assert result['valid_nodes'] == ['X', 'Y'] and len(result['valid_edges']) == 1
    aligned = align_target(result, 'Y', ['X'])
    assert len(aligned['y']['a']) == 40
    assert json.dumps(graph) == before
    (tmp_path / 'X.parquet').write_bytes(b'invalid')
    result = adapt_graph(graph, permissive(), base_dir=tmp_path)
    assert result['valid_nodes'] == ['Y'] and not result['valid_edges']
    assert 'SHA-256' in result['invalid_nodes']['X']['reason']


def test_entity_units_require_explicit_mapping_without_macro_replication(tmp_path):
    graph = graph_with_files(tmp_path)
    file = tmp_path / 'X.parquet'; frame = pd.read_parquet(file)
    frame['entity_id'] = '{"agent_id":1}'
    other = frame.copy(); other.entity_id = '{"agent_id":2}'; other.value += 2
    pd.concat([frame, other]).to_parquet(file)
    graph['nodes'][0]['execution']['a']['series_sha256'] = sha256(file)
    result = adapt_graph(graph, permissive(), base_dir=tmp_path)
    assert result['valid_nodes'] == ['Y']
    assert 'no automatic mean' in result['invalid_nodes']['X']['reason']
    config = permissive(); config['data']['node_overrides'] = {'X': {'entity_mode': 'aggregate', 'aggregation': 'mean'}}
    result = adapt_graph(graph, config, base_dir=tmp_path)
    aligned = align_target(result, 'Y', ['X'])
    assert len(aligned['y']['a']) == 40 and len(aligned['parents']['X']['a']) == 40
    assert np.allclose(np.array(aligned['parents']['X']['a']).ravel(), frame.value + 1)
    assert 'mean' in result['transformations']['X']['a']['formula']
    config['data']['node_overrides']['X'] = {'entity_mode': 'features', 'entity_ids': [{'agent_id': 1}, {'agent_id': 2}]}
    result = adapt_graph(graph, config, base_dir=tmp_path)
    assert np.array(result['series']['X']['a']['values']).shape == (40, 2)


def test_features_constant_broadcast_and_missing_observations(tmp_path):
    graph = graph_with_files(tmp_path); file = tmp_path / 'X.parquet'
    frame = pd.read_parquet(file); other = frame.copy(); other.feature = 'second'; other.value = 9.0
    pd.concat([frame, other]).to_parquet(file)
    graph['nodes'][0]['execution']['a']['series_sha256'] = sha256(file)
    assert 'Multiple features' in adapt_graph(graph, permissive(), base_dir=tmp_path)['invalid_nodes']['X']['reason']
    cfg = permissive(); cfg['data']['node_overrides'] = {'X': {'features': ['value', 'second']}}
    assert 'scalar broadcast' in adapt_graph(graph, cfg, base_dir=tmp_path)['invalid_nodes']['X']['reason']
    cfg['data']['node_overrides']['X'] = {'feature': 'value'}
    assert adapt_graph(graph, cfg, base_dir=tmp_path)['valid_nodes'] == ['X', 'Y']


def test_run_boundaries_and_purged_partition_windows():
    cfg = settings({'rnn': {'max_lag': 2}, 'split': {'run_roles': {'a': 'train', 'b': 'test', 'c': 'validation', 'd': 'confirmation'}}})
    y = {r: np.arange(20) + i * 1000 for i, r in enumerate('abcd')}
    runs, _ = align_runs(y)
    windows = make_windows(runs, cfg)
    assert len(windows['groups']['train']['x']) == 18
    assert np.max(windows['groups']['train']['x']) < 1000
    assert np.min(windows['groups']['test']['x']) >= 1000
    single, _ = align_runs(np.arange(80))
    cfg['split']['run_roles'] = {}
    split = make_windows(single, cfg)
    for role, group in split['groups'].items():
        assert all(np.diff(row[:, 0]).tolist() == [1.0] for row in group['x'])
    assert set(split['groups']['validation']['steps']).isdisjoint(split['groups']['test']['steps'])


def test_real_first_part_logs_are_read_and_not_fabricated():
    for scene in ('fish', 'covasim'):
        file = Path('causal_graph/results/v2_live_20261106') / scene / 'executable_graph.json'
        if not file.exists(): pytest.skip('Locally retained real-log acceptance artifacts absent')
        before = sha256(file)
        result = adapt_graph(file)
        assert result['valid_nodes'] == [] and result['invalid_nodes']
        assert any(r['source_files'] for r in result['data_report'].values())
        assert sha256(file) == before
