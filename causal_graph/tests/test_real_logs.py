"""Actual native simulations and public Trajectory integration, no model API."""
from dataclasses import replace

import pandas as pd
import pytest
from simulations.common.runner import load, run
from simulations.common.trajectory_api import Trajectory

from causal_graph.inputs import inspect_run
from causal_graph.graph_export import assemble_graph
from causal_graph.indicator_runner import execute_indicator
from .fixtures import fixture_outputs, fixture_context
from .validate_logs import additional_raw_check


@pytest.mark.parametrize('model,field', [('fish', 'vx'), ('covasim', 'age')])
def test_real_native_logs_and_generated_function_contract(tmp_path, settings, model, field):
    config = load(f'configs/{model}.yaml')
    config['steps'] = 5
    config['output']['directory'] = str(tmp_path / 'simulation')
    source = run(config)
    inspected = inspect_run(source)
    assert inspected['manifest']['model_name'] == model
    from causal_graph.data_schema import build_data_schema
    schema, _ = build_data_schema([inspected])
    assert field in schema['tables']['agent_states']['fields']
    if model == 'fish':
        nested = schema['tables']['raw_frames']['fields']['frame_json']['json_structure']
        assert {'decisions', 'decision_input', 'positions'} <= set(nested['properties'])
    else:
        assert {'infectious', 'simulation_day', 'age'} <= set(schema['tables']['agent_states']['fields'])
    fixture = fixture_outputs(field)
    context = fixture_context(fixture)
    graph = assemble_graph(context, 'offline_fixture_only', tmp_path)
    reviewed = replace(settings, execution_mode='trusted_reviewed')
    node = graph['nodes'][0]
    review = {'reviewer': 'test fixture author', 'reviewed_at': '2026-11-06',
              'notes': 'Only handwritten test aggregations reviewed; no LLM generation claim.',
              'code_sha256': {node['indicator_id']: node['code_sha256']}}
    result = execute_indicator(node, inspected, tmp_path, reviewed, review)
    assert result['status'] == 'success', result.get('error')
    calculated = pd.read_parquet(tmp_path / result['series_file']).set_index('step')['value']
    expected = Trajectory(source).read('agent_states').groupby('step')[field].mean()
    pd.testing.assert_series_equal(calculated, expected, check_names=False)
    raw_check = tmp_path / 'additional'
    raw_check.mkdir()
    assert additional_raw_check(model, source, raw_check, reviewed)['status'] == 'success'
