from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from causal_graph.graph_export import assemble_graph
from causal_graph.indicator_runner import check_result, execute_indicator, load_approvals
from causal_graph.inputs import inspect_run
from causal_graph.io import save_json
from .fixtures import fixture_outputs


@pytest.mark.parametrize('result,error', [
    ([1, 2], 'Pandas'), (pd.Series([1, 2, 3]), 'explicit step'),
    (pd.DataFrame({'step': [0, 0, 1], 'v': [1, 2, 3]}), 'Duplicate'),
    (pd.DataFrame({'step': [0, 1, 2], 'v': [1, np.inf, 3]}), 'Infinite'),
    (pd.DataFrame({'step': [0, .5, 2], 'v': [1, 2, 3]}), 'integral'),
    (pd.DataFrame({'step': [0, 1, 99], 'v': [1, 2, 3]}), 'unrecorded'),
    (pd.DataFrame({'step': [0, 1, 2], 'v': ['x', 'y', 'z']}), 'Non-numeric'),
    (pd.DataFrame({'step': [0, 1, 2], 'v': [np.nan, np.nan, np.nan]}), 'insufficient')])
def test_result_failures(settings, result, error):
    with pytest.raises(ValueError, match=error):
        check_result(result, 'run', 'indicator', [0, 1, 2], settings)


def test_constants_missing_and_multiple_features(settings):
    result = pd.DataFrame({'step': [0, 1, 2, 3, 4], 'constant': [2] * 5, 'missing': [1, 2, 3, np.nan, np.nan]})
    long, report = check_result(result, 'run', 'indicator', range(5), settings)
    assert len(long) == 10 and len(report['warnings']) == 2
    assert set(long.columns) == {'run_id', 'indicator_id', 'step', 'feature', 'value'}


def make_nodes(tmp_path):
    fixture = fixture_outputs(failing=True)
    context = {k: v for value in fixture.values() for k, v in value.items()}
    return assemble_graph(context, 'offline_fixture', tmp_path)['nodes']


def test_isolation_fails_closed(tmp_path, settings, small_run, monkeypatch):
    nodes = make_nodes(tmp_path)
    monkeypatch.setattr('shutil.which', lambda _: None)
    report = execute_indicator(nodes[0], inspect_run(small_run), tmp_path, settings)
    assert report['status'] == 'failed' and 'Docker is unavailable' in report['error']
    assert not list(tmp_path.glob('indicator_series/**/*.parquet'))


def test_missing_fields_and_review_required(tmp_path, settings, small_run):
    nodes = make_nodes(tmp_path)
    run = inspect_run(small_run)
    report = execute_indicator(nodes[-1], run, tmp_path, settings)
    assert report['error_type'] == 'unavailable_data'
    trusted = replace(settings, execution_mode='trusted_reviewed')
    report = execute_indicator(nodes[0], run, tmp_path, trusted)
    assert report['error_type'] == 'review_required'


def test_reviewed_real_trajectory_success_and_failure(tmp_path, settings, small_run):
    nodes = make_nodes(tmp_path)
    trusted = replace(settings, execution_mode='trusted_reviewed')
    approvals = {'reviewer': 'test fixture reviewer', 'reviewed_at': '2026-11-06',
                 'notes': 'Known artificial fixture functions only.',
                 'code_sha256': {n['indicator_id']: n['code_sha256'] for n in nodes}}
    report = execute_indicator(nodes[0], inspect_run(small_run), tmp_path, trusted, approvals)
    assert report['status'] == 'success', report
    assert not list((tmp_path / 'indicator_code').glob('__pycache__/*'))
    actual = pd.read_parquet(tmp_path / report['series_file'])
    assert len(actual) >= 3 and set(actual.run_id) == {inspect_run(small_run)['manifest']['run_id']}
    nodes[0]['config'] = {'unused': True}
    # A hash mismatch cannot be bypassed by selecting trusted mode.
    approvals['code_sha256']['test_a'] = '0' * 64
    denied = execute_indicator(nodes[0], inspect_run(small_run), tmp_path, trusted, approvals)
    assert denied['error_type'] == 'review_required'


def test_review_file_validation(tmp_path):
    p = tmp_path / 'review.json'
    save_json(p, {'code_sha256': {}})
    with pytest.raises(ValueError, match='requires'):
        load_approvals(p)


def test_reviewed_execution_exception_and_timeout(tmp_path, settings, small_run):
    from causal_graph.io import digest
    nodes = make_nodes(tmp_path)
    node = nodes[0]
    file = tmp_path / node['code_file']
    file.write_text("def compute_indicator(data, config):\n    return data['agent_states']['nonexistent_runtime_field']\n", encoding='utf-8')
    node['code_sha256'] = digest(file)
    review = {'reviewer': 'test fixture author', 'reviewed_at': '2026-11-06',
              'notes': 'Reviewed deliberately failing test code only.', 'code_sha256': {'test_a': node['code_sha256']}}
    report = execute_indicator(node, inspect_run(small_run), tmp_path,
                               replace(settings, execution_mode='trusted_reviewed'), review)
    assert report['status'] == 'failed' and 'nonexistent_runtime_field' in report['error']
    file.write_text("def compute_indicator(data, config):\n    rows = data['agent_states']\n    while True:\n        pass\n", encoding='utf-8')
    node['code_sha256'] = digest(file)
    review['code_sha256']['test_a'] = node['code_sha256']
    report = execute_indicator(node, inspect_run(small_run), tmp_path,
                               replace(settings, execution_mode='trusted_reviewed', indicator_timeout=1), review)
    assert report['status'] == 'failed' and 'TimeoutExpired' in report['error']
