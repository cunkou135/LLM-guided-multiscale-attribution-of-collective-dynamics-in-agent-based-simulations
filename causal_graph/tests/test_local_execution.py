from dataclasses import replace
import json
from pathlib import Path

import pandas as pd
import pytest

from causal_graph.indicator_runner import check_result, execute_indicator, load_approvals
from causal_graph.inputs import inspect_run
from causal_graph.io import read_json, save_json
from causal_graph.pipeline import run_pipeline, PipelineFailure
from .fixtures import OfflineClient, fixture_outputs


def test_entity_series_preserves_values_without_aggregation(settings):
    index = pd.MultiIndex.from_tuples([(1, 7), (0, 7), (2, 7), (0, 8), (1, 8), (2, 8)], names=['step', 'agent_id'])
    original = pd.Series([11., 10., 12., 20., 21., 22.], index=index)
    output, report = check_result(original, 'r', 'i', [0, 1, 2], settings)
    assert len(output) == 6 and report['entities'] == 2 and report['time_steps'] == 3
    assert report['entity_fields'] == ['agent_id']
    for agent, values in [(7, [10., 11., 12.]), (8, [20., 21., 22.])]:
        selected = output[output.entity_id.map(lambda x: json.loads(x)['agent_id'] == agent)]
        assert selected.sort_values('step').value.tolist() == values


def test_entity_duplicates_and_short_entity_fail(settings):
    duplicate = pd.Series([1., 2., 3.], index=pd.MultiIndex.from_tuples([(0, 7), (0, 7), (1, 7)], names=['step', 'agent_id']))
    with pytest.raises(ValueError, match='Duplicate time'):
        check_result(duplicate, 'r', 'i', range(3), settings)
    short = pd.Series([1., 2., 3., 4.], index=pd.MultiIndex.from_tuples([(0, 7), (1, 7), (2, 7), (0, 8)], names=['step', 'agent_id']))
    with pytest.raises(ValueError, match='insufficient actual'):
        check_result(short, 'r', 'i', range(3), settings)


def test_execute_only_after_execution_source_change_makes_no_model_calls(tmp_path, llm, settings, small_run, monkeypatch):
    import causal_graph.pipeline as pipeline
    output = tmp_path / 'experiment'
    client = OfflineClient(fixture_outputs())
    run_pipeline([small_run], llm, settings, output, client=client, generate_only=True)
    graph = read_json(output / 'candidate_graph.json')
    originals = {p.relative_to(output).as_posix(): p.read_bytes() for p in (output / 'generation').rglob('*') if p.is_file()}
    old_software = pipeline.software_provenance
    def changed_software():
        result = old_software()
        result['source_sha256']['indicator_runner.py'] = 'changed-execution-only'
        return result
    monkeypatch.setattr(pipeline, 'software_provenance', changed_software)
    monkeypatch.setattr('causal_graph.llm_client.urlopen', lambda *a, **k: pytest.fail('LLM was called'))
    review = {'reviewer': 'test author', 'reviewed_at': '2026-11-06', 'notes': 'Known fixture only',
              'code_sha256': {n['indicator_id']: n['code_sha256'] for n in graph['nodes']}}
    trusted = replace(settings, execution_mode='trusted_reviewed')
    with pytest.raises(PipelineFailure, match='identity mismatch'):
        run_pipeline([small_run], llm, trusted, output, client=client, resume=True, approvals=review)
    run_pipeline([small_run], llm, trusted, output, client=client, resume=True, approvals=review, execute_only=True)
    assert len(client.calls) == 6
    assert read_json(output / 'pipeline_report.json')['status'] == 'completed'
    assert all((output / name).read_bytes() == data for name, data in originals.items())
    assert read_json(output / 'candidate_graph.json')['edges'] == graph['edges']
    reports = read_json(output / 'execution_report.json')
    assert all(r['status'] == 'success' for r in reports)
    assert len(list(output.glob('execution/*/*/attempt_*/stdout.log'))) == 3


def test_rejected_review_never_starts_process(tmp_path, settings, small_run):
    from .test_indicator import make_nodes
    node = make_nodes(tmp_path)[0]
    file = tmp_path / 'review.json'
    save_json(file, {'reviewer': 'test author', 'reviewed_at': '2026-11-06', 'notes': 'Explicit rejection', 'code_sha256': {},
                     'rejections': {node['indicator_id']: {'code_sha256': node['code_sha256'], 'reason': 'Definition and implementation disagree'}}})
    review = load_approvals(file)
    report = execute_indicator(node, inspect_run(small_run), tmp_path, replace(settings, execution_mode='trusted_reviewed'), review)
    assert report['error_type'] == 'review_rejected' and not report['execution_started']
    assert 'Definition and implementation disagree' in report['error']
    assert not list(tmp_path.glob('execution/**/process.json'))


def test_execute_only_requires_existing_complete_checkpoints(tmp_path, llm, settings, small_run):
    out = tmp_path / 'experiment'
    client = OfflineClient()
    with pytest.raises(ValueError, match='requires resume'):
        run_pipeline([small_run], llm, settings, out, client=client, execute_only=True)
    run_pipeline([small_run], llm, settings, out, client=client, generate_only=True)
    (out / 'generation/codes/checkpoint.json').unlink()
    with pytest.raises(PipelineFailure, match='missing codes checkpoint'):
        run_pipeline([small_run], llm, settings, out, client=client, resume=True, execute_only=True)
    assert len(client.calls) == 6
