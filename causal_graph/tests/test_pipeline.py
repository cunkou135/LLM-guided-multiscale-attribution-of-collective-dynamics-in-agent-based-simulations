from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import shutil

import networkx as nx
import pytest

from causal_graph.cli import main
from causal_graph.inputs import inspect_run, inspect_runs, resolve_runs
from causal_graph.io import read_json, save_json
from causal_graph.pipeline import run_pipeline, PipelineFailure
from .fixtures import OfflineClient, fixture_outputs


def test_generate_resume_reviewed_execution(tmp_path, llm, settings, small_run):
    out = tmp_path / 'experiment'
    client = OfflineClient(fixture_outputs(failing=True))
    run_pipeline([small_run], llm, settings, out, client=client, generate_only=True)
    graph = read_json(out / 'candidate_graph.json')
    assert len(graph['nodes']) == 4 and len(graph['edges']) == 4
    assert len(nx.read_graphml(out / 'candidate_graph.graphml')) == 4
    assert not read_json(out / 'executable_graph.json')['nodes']
    review = {'reviewer': 'test suite author', 'reviewed_at': '2026-11-06', 'notes': 'Only known artificial fixture code reviewed.',
              'code_sha256': {n['indicator_id']: n['code_sha256'] for n in graph['nodes'] if n['code_sha256']}}
    run_pipeline([small_run], llm, replace(settings, execution_mode='trusted_reviewed'), out,
                 client=client, resume=True, approvals=review)
    assert len(client.calls) == 6
    assert read_json(out / 'candidate_graph.json')['edges'] == graph['edges']
    assert len(read_json(out / 'candidate_graph.json')['nodes']) == len(graph['nodes'])
    executable = read_json(out / 'executable_graph.json')
    assert len(executable['nodes']) == 3 and len(executable['excluded_edges']) == 1
    assert len(read_json(out / 'execution_report.json')) == 4
    assert read_json(out / 'pipeline_report.json')['status'] == 'completed_with_failures'
    assert read_json(out / 'experiment.json')['client_mode'] == 'offline_fixture_not_model_generated'
    assert len(list(out.glob('invocations/*/execution_report.json'))) == 2


def test_interruption_and_resume_preserves_calls(tmp_path, llm, settings, small_run):
    class Interrupted(OfflineClient):
        def complete(self, messages, directory):
            if len(self.calls) == 2:
                raise RuntimeError('Simulated transport interruption')
            return super().complete(messages, directory)
    out = tmp_path / 'experiment'
    client = Interrupted()
    with pytest.raises(PipelineFailure, match='interruption'):
        run_pipeline([small_run], llm, settings, out, client=client, generate_only=True)
    assert read_json(out / 'experiment.json')['status'] == 'failed'
    resumed = OfflineClient()
    run_pipeline([small_run], llm, settings, out, client=resumed, generate_only=True, resume=True)
    assert [call[0] for call in resumed.calls] == ['codes', 'edges_upward', 'edges_downward', 'edges_intrascale']
    assert (out / 'generation/codes/attempt_000/validation.json').exists()
    assert len(list(out.glob('invocations/*/failure_traceback.txt'))) == 1


def test_resume_model_and_content_mismatch(tmp_path, llm, settings, small_run):
    out = tmp_path / 'experiment'
    client = OfflineClient()
    run_pipeline([small_run], llm, settings, out, client=client, generate_only=True)
    original = read_json(out / 'experiment.json')
    with pytest.raises(PipelineFailure, match='identity mismatch'):
        run_pipeline([small_run], replace(llm, model='other-model'), settings, out, client=client,
                     generate_only=True, resume=True)
    assert read_json(out / 'experiment.json') == original
    (out / 'generation/phenomena/attempt_000/response.txt').write_text('tampered')
    with pytest.raises(PipelineFailure, match='original response changed'):
        run_pipeline([small_run], llm, settings, out, client=client, generate_only=True, resume=True)


def test_distinct_model_experiments(tmp_path, llm, settings, small_run):
    for index in range(2):
        run_pipeline([small_run], replace(llm, model=f'model-{index}'), settings, tmp_path / str(index),
                     client=OfflineClient(), generate_only=True)
    assert read_json(tmp_path / '0/experiment.json')['llm']['model'] != read_json(tmp_path / '1/experiment.json')['llm']['model']


def test_resume_rejects_schema_change_and_keeps_v1_archives(tmp_path, llm, settings, small_run, monkeypatch):
    import causal_graph.pipeline as pipeline
    out = tmp_path / 'experiment'
    client = OfflineClient()
    run_pipeline([small_run], llm, settings, out, client=client, generate_only=True)
    original = pipeline.build_data_schema
    def changed(runs):
        schema, audit = original(runs)
        schema['new_contract_metadata'] = 'changed'
        return schema, audit
    monkeypatch.setattr(pipeline, 'build_data_schema', changed)
    with pytest.raises(PipelineFailure, match='identity mismatch'):
        run_pipeline([small_run], llm, settings, out, client=client, generate_only=True, resume=True)
    archive = Path('causal_graph/examples/offline_acceptance_20261106/fish_offline_experiment/candidate_graph.json')
    assert read_json(archive)['schema_version'] == '1.0'


def test_input_corruption_and_run_id_resolution(tmp_path, small_run):
    assert resolve_runs(run_ids=[small_run.name], runs_root=small_run.parent) == [small_run.resolve()]
    with pytest.raises(ValueError):
        resolve_runs(run_ids=['../escape'])
    with pytest.raises(ValueError, match='Duplicate input'):
        inspect_runs([small_run, small_run])
    copied = tmp_path / 'copied'
    shutil.copytree(small_run, copied)
    (copied / 'scenario.md').write_text('changed scenario')
    with pytest.raises(ValueError, match='hash mismatch'):
        inspect_run(copied)


def test_incomplete_inputs_and_cli_help(tmp_path):
    with pytest.raises(ValueError, match='missing manifest'):
        inspect_run(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(['--help'])
    assert exc.value.code == 0
