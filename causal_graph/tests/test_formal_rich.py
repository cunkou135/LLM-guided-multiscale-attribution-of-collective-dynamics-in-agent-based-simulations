"""Broad generation budgets and immutable small-experiment prompt compatibility."""
import json
from pathlib import Path
import zipfile
from dataclasses import replace

import pytest

from causal_graph.config import PipelineConfig, load_llm, load_pipeline
from causal_graph.prompts import build_messages, template_version
from .fixtures import fixture_context


CONFIG = Path(__file__).resolve().parents[1] / 'configs'


def test_formal_scope_preserves_units_and_defensible_edges():
    limits = load_pipeline(CONFIG / 'formal_rich.yaml')
    llm = load_llm(CONFIG / 'deepseek_flash_formal.yaml')
    assert (limits.max_phenomena, limits.max_indicators, limits.max_edges) == (8, 72, 720)
    assert limits.execution_mode == 'trusted_reviewed'
    assert llm.model == 'deepseek-flash' and llm.stream
    context = fixture_context()
    variables = json.loads(build_messages('indicators', 'fixture', context, limits)[1]['content'])
    code = json.loads(build_messages('codes', 'fixture', context, limits)[1]['content'])
    assert variables['template_version'].endswith('/broad-2')
    assert 'different numbers at each scale' in variables['task']
    assert 'Do not average entity/event outputs' in code['task']
    for stage in ('edges_upward', 'edges_downward', 'edges_intrascale'):
        payload = json.loads(build_messages(stage, 'fixture', context, limits)[1]['content'])
        assert '240 edges' in payload['task']
        assert 'Do not fill a quota' in payload['task']
        assert 'data_schema' not in payload


def test_published_small_experiment_prompts_stay_byte_compatible():
    limits = PipelineConfig(max_phenomena=2, max_indicators=6, max_edges=24)
    assert template_version(limits) == 'observed-schema-three-directions/2.0'
    archive = CONFIG.parent / 'examples/v2_live_20261106/fish_complete_experiment.zip'
    with zipfile.ZipFile(archive) as z:
        load = lambda name: json.loads(z.read(name))
        scenario = z.read('scenario.md').decode('utf-8').replace('\r\n', '\n')
        context = {'data_schema': load('data_schema.json')}
        for stage in ('phenomena', 'indicators', 'codes', 'edges_upward', 'edges_downward', 'edges_intrascale'):
            checkpoint = load(f'generation/{stage}/checkpoint.json')
            expected = load(checkpoint['generation_call'] + '/prompt.json')
            assert build_messages(stage, scenario, context, limits) == expected, stage
            context.update(load(f'generation/{stage}/parsed.json'))


def test_code_batches_resume_and_verify_all_original_responses(tmp_path):
    from causal_graph.generation import generate_codes
    from causal_graph.graph_export import assemble_graph
    from causal_graph.io import read_json
    from .fixtures import OfflineClient, fixture_outputs
    original = fixture_outputs()

    class Batches(OfflineClient):
        def complete(self, messages, directory):
            if getattr(self, 'interrupt', False) and self.calls:
                raise RuntimeError('Interrupted after first batch')
            definitions = json.loads(messages[1]['content'])['prior_generated_definitions']['indicators']
            ids = {n['indicator_id'] for n in definitions}
            self.outputs = {**original, 'codes': {'codes': [c for c in original['codes']['codes'] if c['indicator_id'] in ids]}}
            return super().complete(messages, directory)

    context = fixture_context()
    limits = replace(load_pipeline(CONFIG / 'formal_rich.yaml'), code_batch_size=2)
    first = Batches(); first.interrupt = True
    with pytest.raises(RuntimeError, match='Interrupted'):
        generate_codes('fixture', context, limits, first, tmp_path)
    client = Batches()
    parsed, call = generate_codes('fixture', context, limits, client, tmp_path)
    assert len(client.calls) == 1 and len(parsed['codes']) == 3
    graph = assemble_graph({**context, 'codes': parsed['codes']}, call, tmp_path)
    assert all('/batches/' in n['generation_call'] for n in graph['nodes'])
    assert read_json(tmp_path / call / 'assembly.json')['model_request_made'] is False
    cached = Batches()
    assert generate_codes('fixture', context, limits, cached, tmp_path) == (parsed, call)
    assert not cached.calls
    path = tmp_path / graph['nodes'][0]['generation_call'] / 'response.txt'
    path.write_text('tampered', encoding='utf-8')
    with pytest.raises(ValueError, match='original response changed'):
        generate_codes('fixture', context, limits, Batches(), tmp_path)


def test_explicit_source_upgrade_rechecks_original_code_without_new_code_calls(tmp_path, llm, settings, small_run, monkeypatch):
    from copy import deepcopy
    import causal_graph.pipeline as pipeline
    import causal_graph.schemas as schemas
    from causal_graph.io import read_json
    from .fixtures import OfflineClient
    original_analyzer = schemas.analyze_access
    def old_false_positive(*args):
        report = original_analyzer(*args)
        return {**report, 'errors': report['errors'] + ['Simulated old derived-field false positive']}
    monkeypatch.setattr(schemas, 'analyze_access', old_false_positive)
    output = tmp_path / 'experiment'
    with pytest.raises(pipeline.PipelineFailure):
        pipeline.run_pipeline([small_run], llm, settings, output, client=OfflineClient(), generate_only=True)
    response = output / 'generation/codes/attempt_000/response.txt'
    before = response.read_bytes()
    monkeypatch.setattr(schemas, 'analyze_access', original_analyzer)
    provenance = pipeline.software_provenance
    def upgraded():
        record = deepcopy(provenance())
        record['source_sha256']['code_contract.py'] = 'f' * 64
        return record
    monkeypatch.setattr(pipeline, 'software_provenance', upgraded)
    with pytest.raises(pipeline.PipelineFailure, match='identity mismatch'):
        pipeline.run_pipeline([small_run], llm, settings, output, client=OfflineClient(), resume=True, generate_only=True)
    client = OfflineClient()
    pipeline.run_pipeline([small_run], llm, settings, output, client=client, resume=True, generate_only=True,
                          resume_source_upgrade=True)
    assert [c[0] for c in client.calls] == ['edges_upward', 'edges_downward', 'edges_intrascale']
    assert response.read_bytes() == before
    assert not read_json(response.parent / 'validation.json')['valid']
    assert read_json(next(response.parent.glob('revalidation_*.json')))['valid']
    assert list(output.glob('invocations/*/generation_source_upgrade.json'))
    assert read_json(output / 'pipeline_report.json')['status'] == 'generated_only'
    assert not any(r['status'] == 'success' for r in read_json(output / 'execution_report.json'))
    with pytest.raises(pipeline.PipelineFailure, match='identity mismatch'):
        pipeline.run_pipeline([small_run], replace(llm, model='other-model'), settings, output, client=OfflineClient(),
                              resume=True, generate_only=True, resume_source_upgrade=True)


@pytest.mark.parametrize('stage', ['edges_upward', 'edges_downward', 'edges_intrascale'])
def test_edge_partitions_cover_all_eligible_pairs_and_preserve_raw_origins(tmp_path, stage):
    from causal_graph.generation import generate_edges
    from causal_graph.io import read_json, save_json
    from causal_graph.schemas import EDGE_STAGES, classify_direction
    context = fixture_context()
    prototypes = context['indicators']
    context['indicators'] = [{**n, 'indicator_id': f'{n["indicator_id"]}_{i}', 'name': f'{n["name"]} {i}'}
                             for i in range(6) for n in prototypes]
    limits = load_pipeline(CONFIG / 'formal_rich.yaml')
    class Pairs:
        mode = 'offline_fixture_not_scientific_output'
        def __init__(self): self.calls = []
        def complete(self, messages, directory):
            payload = json.loads(messages[1]['content'])
            nodes = payload['prior_generated_definitions']['indicators']
            sources = payload['eligible_source_ids']
            self.calls.append(sources)
            pairs = [(a, b) for a in nodes for b in nodes if a['indicator_id'] in sources and
                     a['indicator_id'] != b['indicator_id'] and classify_direction(a['scale'], b['scale']) == EDGE_STAGES[stage]]
            body = {'edges': [{'edge_id': 'raw_repeated_id', 'source': a['indicator_id'], 'target': b['indicator_id'],
                    'scale_direction': EDGE_STAGES[stage], 'relation_type': 'semantic_candidate',
                    'semantic_rationale': 'EXHAUSTIVE STRUCTURAL FIXTURE ONLY; no scientific mechanism.'}
                    for i, (a, b) in enumerate(pairs)]}
            directory.mkdir(parents=True)
            save_json(directory / 'response.txt', body)
            return json.dumps(body)
    client = Pairs()
    parsed, call = generate_edges(stage, 'fixture', context, limits, client, tmp_path)
    expected = {(a['indicator_id'], b['indicator_id']) for a in context['indicators'] for b in context['indicators']
                if a != b and classify_direction(a['scale'], b['scale']) == EDGE_STAGES[stage]}
    assert {(e['source'], e['target']) for e in parsed['edges']} == expected
    assert len(client.calls) == 4
    all_sources = [s for part in client.calls for s in part]
    assert len(all_sources) == len(set(all_sources))
    plan = read_json(tmp_path / 'generation' / stage / 'partition_plan.json')
    assert sum(p['edge_budget'] for p in plan['partitions']) == limits.max_edges // 3
    assert max(p['edge_budget'] for p in plan['partitions']) <= 60
    origins = read_json(tmp_path / call / 'assembly.json')['edge_origins']
    for edge, origin in zip(parsed['edges'], origins):
        original = read_json(tmp_path / origin['call'] / 'response.txt')['edges'][origin['row_index']]
        assert origin['original_edge_id'] == original['edge_id']
        assert all(edge[k] == original[k] for k in original if k != 'edge_id')
    cached = Pairs()
    assert generate_edges(stage, 'fixture', context, limits, cached, tmp_path) == (parsed, call)
    assert not cached.calls
    # A legacy duplicate-ID rejection can be rechecked without rewriting raw output.
    raw_call = tmp_path / origins[0]['call']
    raw_before = (raw_call / 'response.txt').read_bytes()
    save_json(raw_call / 'validation.json', {'valid': False, 'errors': ['Legacy duplicate ID rejection, fixture only']})
    (raw_call.parent / 'checkpoint.json').unlink()
    (tmp_path / 'generation' / stage / 'checkpoint.json').unlink()
    from causal_graph.io import digest
    save_json(tmp_path / 'artifact_hashes.json', {p.relative_to(tmp_path).as_posix(): digest(p)
                                                for p in tmp_path.rglob('*') if p.is_file()})
    upgraded = Pairs(); upgraded.revalidate_saved = True
    assert generate_edges(stage, 'fixture', context, limits, upgraded, tmp_path) == (parsed, call)
    assert not upgraded.calls and (raw_call / 'response.txt').read_bytes() == raw_before
    assert not read_json(raw_call / 'validation.json')['valid']
    assert read_json(next(raw_call.glob('revalidation_*.json')))['valid']
