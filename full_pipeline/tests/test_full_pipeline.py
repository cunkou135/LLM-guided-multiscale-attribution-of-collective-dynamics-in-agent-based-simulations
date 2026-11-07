"""Explicit mock-LLM control tests; observations come from the actual small Fish runner."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import json

import pytest
import yaml

from causal_graph.io import digest, read_json, save_json
from causal_graph.tests.fixtures import fixture_outputs
from causal_discovery.pipeline import run_pipeline as discover
from causal_discovery.m1_data import adapt_graph
from causal_discovery.m5_graph import integrate_graph
from full_pipeline.main import filesystem_path, load_config, load_configured_credential, run_full_pipeline
from full_pipeline.scenario_adapter import ROOT, match_scenario, prepare_run, simulation_config
from full_pipeline.stage_manager import QualityError, StageFailure, StageManager
from full_pipeline.validators import REVIEW_CHECKS, definition_hash, issue


class MockLLM:
    mode = 'explicit_mock_control_test_not_research_evidence'

    def __init__(self, failures=None, runtime_failure=False, empty_edges=False):
        self.calls = []; self.failures = failures or {}; self.runtime_failure = runtime_failure
        self.outputs = fixture_outputs(); self.empty_edges = empty_edges

    def complete(self, messages, directory):
        directory.mkdir(parents=True, exist_ok=False)
        payload = json.loads(messages[1]['content']); stage = payload['generation_task']
        definitions = payload['prior_generated_definitions'].get('indicators', [])
        ids = [n['indicator_id'] for n in definitions]
        task = stage + (':' + ids[0] if stage == 'codes' else '')
        self.calls.append(task)
        save_json(directory / 'request.json', {'messages': messages, 'mock_only': True})
        value = deepcopy(self.outputs[stage])
        if stage == 'codes':
            value['codes'] = [n for n in value['codes'] if n['indicator_id'] in ids]
            if self.runtime_failure and task == 'codes:test_b' and self.calls.count(task) == 1:
                value['codes'][0]['python_code'] = "def compute_indicator(data, config):\n    values = data['agent_states'].groupby('step')['agent_id'].var()\n    raise ValueError('intentional mock implementation failure')\n"
        if self.empty_edges and stage.startswith('edges_'): value = {'edges': []}
        if self.calls.count(task) <= self.failures.get(task, 0):
            if stage == 'indicators': value['indicators'][0]['required_data']['agent_states'].append('fabricated_field')
            elif stage.startswith('edges_'):
                value = {'edges': [{**self.outputs['edges_downward']['edges'][0], 'target': 'absent'}]}
            elif stage == 'codes': value['codes'][0]['python_code'] = 'def broken('
            else:
                (directory / 'response.txt').write_text('{broken json', encoding='utf-8')
                return '{broken json'
        raw = json.dumps(value)
        (directory / 'response.txt').write_text(raw, encoding='utf-8')
        save_json(directory / 'response_metadata.json', {'actual_model': None, 'mock_only': True})
        return raw


@pytest.fixture(scope='module')
def control_config(tmp_path_factory):
    directory = tmp_path_factory.mktemp('full_pipeline_controls')
    cfg = yaml.safe_load((ROOT / 'configs/fish.yaml').read_text(encoding='utf-8'))
    cfg['parameters']['population']['count'] = 12
    file = directory / 'explicit_small_fish_mock_control.yaml'
    file.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    return {'experiment_mode': 'interface_test', 'simulation': {'seeds': [11], 'additional_seeds': [], 'max_total_runs': 1,
                'steps': {'fish': 5}, 'configs': {'fish': str(file)}, 'supplement_for_coverage': False},
            'output': {'root': str(directory / 'cache')},
            'stage1': {'pipeline_config': 'causal_graph/configs/pipeline.yaml',
                       'pipeline_overrides': {'max_phenomena': 1, 'max_indicators': 3, 'max_edges': 12}}}


def approve_fixture(root):
    graph = read_json(root / 'internal/stage1/current_candidate.json')
    review = {'reviewer': 'test author reviewing known MOCK fixture source, not a human research approval',
              'reviewed_at': '2026-11-07', 'notes': 'Only the explicit mock groupby mean/var/sum and intentional failure control are reviewed.',
              'reviews': {n['indicator_id']: {'code_sha256': n['code_sha256'], 'definition_sha256': definition_hash(n),
                    'verdict': 'approved', 'checks': {k: True for k in REVIEW_CHECKS}} for n in graph['nodes']}}
    save_json(root / 'internal/stage1/review.json', review)


def start(tmp_path, control_config, client):
    root = tmp_path / 'experiment'
    result = run_full_pipeline(ROOT / 'scenarios/fish.md', output=root, overrides=control_config, client=client)
    assert result['status'] == 'review_required'
    assert not (root / 'stage1_graph.json').exists()
    return root


def test_complete_flow_real_subprocess_data_empty_final_and_metadata(tmp_path, control_config):
    client = MockLLM(); root = start(tmp_path, control_config, client)
    assert Counter(client.calls) == {'phenomena': 1, 'indicators': 1, 'codes:test_a': 1, 'codes:test_b': 1, 'codes:test_c': 1}
    approve_fixture(root); result = run_full_pipeline(resume=root, client=client)
    assert result['status'] == 'completed' and result['stage1_nodes'] == 3 and result['final_nodes'] == 0
    first = read_json(root / 'stage1_graph.json'); final = read_json(root / 'final_causal_graph.json')
    assert len(first['nodes']) == 3 and len(first['edges']) == 3
    assert not final['nodes'] and not final['edges'] and result['stage2_outcome'] == 'no_analyzable_nodes'
    definitions = {n['indicator_id']: n for n in client.outputs['indicators']['indicators']}
    for node in first['nodes']:
        assert node['mathematical_definition'] == definitions[node['node_id']]['mathematical_definition']
        for record in node['execution'].values(): assert digest(record['series_file']) == record['series_sha256']
    before = list(client.calls)
    run_full_pipeline(resume=root, client=client)
    assert client.calls == before  # Even an empty statistical graph never drives generation.


@pytest.mark.parametrize('failure', ['indicators', 'codes:test_b', 'edges_downward'])
def test_only_failing_generation_task_retries(tmp_path, control_config, failure):
    client = MockLLM({failure: 1}); root = start(tmp_path, control_config, client)
    approve_fixture(root); result = run_full_pipeline(resume=root, client=client)
    assert result['status'] == 'completed'
    counts = Counter(client.calls)
    assert counts[failure] == 2 and all(count == 1 for task, count in counts.items() if task != failure)
    prompts = list((filesystem_path(root) / 'internal/checkpoints').rglob('actual_prompt.json'))
    repairs = [read_json(p) for p in prompts if len(read_json(p)) > 2]
    assert len(repairs) == 1 and 'validation_errors' in repairs[0][-1]['content']


def test_runtime_failure_regenerates_only_one_code_and_requires_fresh_review(tmp_path, control_config):
    client = MockLLM(runtime_failure=True); root = start(tmp_path, control_config, client)
    approve_fixture(root); result = run_full_pipeline(resume=root, client=client)
    assert result['status'] == 'review_required'
    assert [p['indicator_id'] for p in read_json(root / 'internal/stage1/review_request.json')['pending']] == ['test_b']
    counts = Counter(client.calls)
    assert counts['codes:test_b'] == 2 and counts['edges_upward'] == counts['edges_downward'] == 0
    approve_fixture(root); result = run_full_pipeline(resume=root, client=client)
    assert result['status'] == 'completed'
    after = Counter(client.calls)
    assert all(after[name] == count for name, count in counts.items())
    assert all(after[stage] == 1 for stage in ('edges_upward','edges_downward','edges_intrascale'))
    reports = list((filesystem_path(root) / 'internal/stage1/builds').glob('*/execution/*/test_b/attempt_*/report.json'))
    assert any(read_json(p)['status'] == 'failed' for p in reports) and any(read_json(p)['status'] == 'success' for p in reports)


def test_maximum_attempts_persist_across_resume(tmp_path, control_config):
    client = MockLLM({'indicators': 20}); root = tmp_path / 'experiment'
    with pytest.raises(StageFailure, match='maximum 3'):
        run_full_pipeline(ROOT / 'scenarios/fish.md', output=root, overrides=control_config, client=client)
    assert Counter(client.calls)['indicators'] == 3 and read_json(root / 'pipeline_report.json')['status'] == 'failed'
    with pytest.raises(StageFailure, match='maximum 3'): run_full_pipeline(resume=root, client=client)
    assert Counter(client.calls)['indicators'] == 3


def test_stage2_failure_resume_has_no_generation_calls(tmp_path, control_config):
    client = MockLLM(); root = start(tmp_path, control_config, client); approve_fixture(root)
    def failed(*args, **kwargs): raise RuntimeError('intentional stage2 engineering failure')
    with pytest.raises(StageFailure, match='stage2 engineering failure'):
        run_full_pipeline(resume=root, client=client, stage2_function=failed)
    counts = list(client.calls); first_hash = digest(root / 'stage1_graph.json')
    result = run_full_pipeline(resume=root, client=client)
    assert result['status'] == 'completed' and client.calls == counts and digest(root / 'stage1_graph.json') == first_hash


def test_stale_definition_review_does_not_authorize_execution(tmp_path, control_config):
    client = MockLLM(); root = start(tmp_path, control_config, client); approve_fixture(root)
    review_file = root / 'internal/stage1/review.json'
    review = read_json(review_file); review['reviews']['test_a']['definition_sha256'] = '0' * 64
    save_json(review_file, review)
    calls = list(client.calls)
    result = run_full_pipeline(resume=root, client=client)
    assert result['status'] == 'review_required' and client.calls == calls
    assert not list((filesystem_path(root) / 'internal/stage1/builds').rglob('process.json'))


def test_valid_nodes_zero_accepted_edges_do_not_trigger_generation(tmp_path, control_config):
    # Explicit stage2 integration-control double: actual M1/M5, no statistical claim.
    cfg = deepcopy(control_config)
    cfg['simulation'].update(seeds=[11, 22, 33, 44], max_total_runs=4, steps={'fish': 160})
    client = MockLLM(empty_edges=True); client.outputs = fixture_outputs(field='x')
    root = start(tmp_path, cfg, client); approve_fixture(root)
    def zero_evidence(source, output, config):
        graph = read_json(source); data = adapt_graph(source, config)
        assert len(data['valid_nodes']) == 3
        final = integrate_graph(graph, data, [], [], [], config)['graph']
        output = Path(output); audit = output.parent / (output.stem + '_audit')
        save_json(audit / 'm1_data.json', data); save_json(audit / 'm2_lag_results.json', [])
        save_json(audit / 'm3_granger_results.json', []); save_json(audit / 'm4_pid_results.json', [])
        save_json(audit / 'parameters.json', config); save_json(output, final)
        return {'report': {'status': 'completed', 'explicit_control_double': True}}
    result = run_full_pipeline(resume=root, client=client, stage2_function=zero_evidence)
    assert result['final_nodes'] == 3 and result['final_edges'] == 0
    calls = list(client.calls)
    result = run_full_pipeline(resume=root, client=client, stage2_function=zero_evidence)
    assert result['status'] == 'completed' and client.calls == calls


def test_content_dependencies_invalidate_only_affected_downstream_and_detect_tampering(tmp_path):
    manager = StageManager(tmp_path); calls = Counter()
    def action(name):
        def compute(folder, previous): calls[name] += 1; return {'value': calls[name]}
        return compute
    manager.run('phenomena', {'scenario': 1}, action('p'))
    manager.run('code_A', {'definition': 1}, action('c'))
    manager.run('edges_upward', {'definitions': [1]}, action('u'))
    manager.run('edges_downward', {'definitions': [1]}, action('d'))
    manager.run('code_A', {'definition': 2}, action('c'))
    manager.run('edges_upward', {'definitions': [2]}, action('u'))
    manager.run('edges_downward', {'definitions': [2]}, action('d'))
    manager.run('phenomena', {'scenario': 1}, action('p'))
    assert calls == {'p': 1, 'c': 2, 'u': 2, 'd': 2}
    manager.invalidate('edges_downward', {'definitions': [2]}, [issue('edges_downward', 'relation_direction', 'bad direction')])
    manager.run('edges_downward', {'definitions': [2]}, action('d'))
    manager.run('edges_upward', {'definitions': [2]}, action('u'))
    assert calls['d'] == 3 and calls['u'] == 2
    result = manager.directory('code_A', {'definition': 2}) / 'attempt_000/result.json'
    result.write_text('{}', encoding='utf-8')
    with pytest.raises(StageFailure, match='artifact changed'): manager.run('code_A', {'definition': 2}, action('c'))


def test_scenario_exact_identity_and_unregistered_refusal(tmp_path):
    assert match_scenario(ROOT / 'scenarios/fish.md')['model'] == 'fish'
    assert match_scenario(ROOT / 'scenarios/v2/covasim.md')['scenario_version'] == '2.0'
    unknown = tmp_path / 'scenario.md'; unknown.write_text('A similar fish school', encoding='utf-8')
    with pytest.raises(ValueError, match='Unsupported scenario'): match_scenario(unknown)


def test_explicit_private_credential_source_and_environment_priority(tmp_path, monkeypatch):
    from causal_graph.config import load_llm
    import os
    llm = load_llm(ROOT / 'causal_graph/configs/deepseek_flash.yaml')
    monkeypatch.delenv(llm.api_key_env, raising=False)
    file = tmp_path / 'private.json'; save_json(file, {'api_key': 'LOCAL_TEST_VALUE_NOT_A_REAL_KEY'})
    cfg = load_config(overrides={'stage1': {'credential_file': str(file)}})
    load_configured_credential(cfg, llm)
    assert os.environ[llm.api_key_env] == 'LOCAL_TEST_VALUE_NOT_A_REAL_KEY'
    monkeypatch.setenv(llm.api_key_env, 'EXISTING_TEST_VALUE')
    load_configured_credential(cfg, llm)
    assert os.environ[llm.api_key_env] == 'EXISTING_TEST_VALUE'


def test_simulation_cache_identity_includes_parameters_seed_logging_and_content(tmp_path, control_config):
    cfg = load_config(overrides=control_config)
    scenario = match_scenario(ROOT / 'scenarios/fish.md')
    simulation = simulation_config(scenario, cfg['simulation'], 11, tmp_path / 'runs')
    first = prepare_run(scenario, simulation, tmp_path / 'cache', True)
    second = prepare_run(scenario, simulation, tmp_path / 'cache', True)
    assert first['directory'] == second['directory'] and second['reused']
    changed = deepcopy(simulation); changed['seed'] = 22
    third = prepare_run(scenario, changed, tmp_path / 'cache', True)
    assert third['directory'] != first['directory']
    (Path(first['directory']) / 'agent_states.parquet').write_bytes(b'changed')
    with pytest.raises(ValueError, match='Input changed'): prepare_run(scenario, simulation, tmp_path / 'cache', True)
