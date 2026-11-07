"""Selective-repair regressions using explicit mock replies and actual small logs."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import json

import pytest

from causal_graph.io import read_json, save_json
from full_pipeline.main import ROOT, filesystem_path, run_full_pipeline
from full_pipeline.stage_manager import StageFailure, StageManager, QualityError
from full_pipeline.validators import issue
from full_pipeline.tests.test_full_pipeline import MockLLM, control_config, approve_fixture, start


def test_partial_batch_preserves_valid_siblings_and_detects_original_response_change(tmp_path, control_config):
    cfg = deepcopy(control_config); cfg['stage1']['pipeline_overrides']['code_batch_size'] = 3
    client = MockLLM({'codes:test_a':1})
    root = start(tmp_path,cfg,client)
    assert Counter(client.calls) == {'phenomena':1,'indicators':1,'codes:test_a':2}
    approve_fixture(root); assert run_full_pipeline(resume=root,client=client)['status'] == 'completed'
    graph = read_json(root/'stage1_graph.json')
    unchanged = next(n for n in graph['nodes'] if n['node_id']=='test_b')
    response = Path(unchanged['generation_call'])/'response.txt'
    calls = list(client.calls); response.write_text('tampered original batch',encoding='utf-8')
    with pytest.raises(StageFailure,match='SHA-256 mismatch'): run_full_pipeline(resume=root,client=client)
    assert client.calls == calls


def test_stricter_validation_repairs_only_the_rejected_intact_cached_stage(tmp_path):
    manager=StageManager(tmp_path); requested=[]
    def action(folder,previous):
        requested.append(previous)
        return {'count':3 if not previous else 12}
    assert manager.run('variables',{'input':'fixed'},action)['count']==3
    def require(value):
        if value['count']<12: raise QualityError([issue('indicators','incomplete_definition','at least 12 required')])
    assert manager.run('variables',{'input':'fixed'},action,validator=require,retry=True)['count']==12
    manager.run('variables',{'input':'fixed'},action,validator=require,retry=True)
    assert len(requested)==2 and len(list(manager.root.rglob('invalidations/*.json')))==1


def test_definition_repair_changes_only_that_code_and_resumes_without_repeating_phenomena(tmp_path,control_config):
    class RepairClient(MockLLM):
        def complete(self,messages,directory):
            payload=json.loads(messages[1]['content'])
            if payload.get('definitions_to_repair'):
                self.calls.append('indicators:repair:test_a'); directory.mkdir(parents=True)
                nodes=deepcopy(payload['definitions_to_repair'])
                for node in nodes: node['computation_notes']+=' Explicit snapshot resolution is one platform step.'
                raw=json.dumps({'indicators':nodes})
                (directory/'response.txt').write_text(raw,encoding='utf-8')
                return raw
            return super().complete(messages,directory)
    client=RepairClient(); root=start(tmp_path,control_config,client); approve_fixture(root)
    file=root/'internal/stage1/review.json'; review=read_json(file)
    review['reviews']['test_a'].update(verdict='rejected',repair_stage='indicators',reason='Missing explicit snapshot resolution in definition notes')
    save_json(file,review)
    assert run_full_pipeline(resume=root,client=client)['status']=='review_required'
    counts=Counter(client.calls)
    assert counts['phenomena']==counts['indicators']==counts['indicators:repair:test_a']==1
    assert counts['codes:test_a']==2 and counts['codes:test_b']==counts['codes:test_c']==1
    pending=read_json(root/'internal/stage1/review_request.json')['pending']
    assert [p['indicator_id'] for p in pending]==['test_a']
    approve_fixture(root); assert run_full_pipeline(resume=root,client=client)['status']=='completed'
    final=Counter(client.calls)
    assert all(final[name]==count for name,count in counts.items())
    assert len(list((root/'internal/stage1/definition_revisions').glob('revision_*.json')))==1


def test_stage1_ready_cache_skips_assembly_and_indicator_execution(tmp_path,control_config,monkeypatch):
    import importlib
    module=importlib.import_module('full_pipeline.main')
    client=MockLLM(); root=start(tmp_path,control_config,client); approve_fixture(root)
    run_full_pipeline(resume=root,client=client)
    def forbidden(*args,**kwargs): raise AssertionError('Verified stage1 must not assemble or execute again')
    monkeypatch.setattr(module,'assemble_graph',forbidden); monkeypatch.setattr(module,'execute_indicator',forbidden)
    assert run_full_pipeline(resume=root,client=client)['status']=='completed'


def test_analysis_contract_connects_execution_m1_edges_and_real_stage2(tmp_path, control_config, monkeypatch):
    """Small explicit control budget, actual subprocess metrics and existing M1–M5."""
    import importlib
    from causal_graph.tests.fixtures import fixture_outputs
    from full_pipeline.tests.test_research_contract import contract
    module = importlib.import_module('full_pipeline.main')
    cfg = deepcopy(control_config)
    cfg['simulation'].update(seeds=[11,22,33,44], max_total_runs=4, steps={'fish':160})
    cfg['stage1']['pipeline_overrides'].update(require_analysis_contract=True,
        min_indicators_per_scale=1, target_indicators_per_scale=1)
    client = MockLLM(empty_edges=True)
    client.outputs = fixture_outputs(field='x')
    client.outputs['phenomena']['phenomena'][0].update(
        definition='Explicit interface control only.', scenario_basis='Recorded Fish positions; no scientific phenomenon claim.')
    for node in client.outputs['indicators']['indicators']:
        node['analysis_contract'] = contract(False)
        node['analysis_contract']['analysis_definition'] = node['mathematical_definition']
    events = []
    original_m1, original_execute, original_complete = module.adapt_graph, module.execute_indicator, client.complete
    def execute(*args, **kwargs):
        result = original_execute(*args, **kwargs)
        assert result['status'] == 'success'
        events.append('execution')
        return result
    def admit(*args, **kwargs):
        result = original_m1(*args, **kwargs)
        assert len(result['valid_nodes']) == 3
        events.append('M1')
        return result
    def complete(messages, directory):
        task = json.loads(messages[1]['content'])['generation_task']
        if task.startswith('edges_'):
            assert events.count('execution') == 12 and 'M1' in events
            events.append(task)
        return original_complete(messages, directory)
    monkeypatch.setattr(module, 'execute_indicator', execute)
    monkeypatch.setattr(module, 'adapt_graph', admit)
    client.complete = complete
    root = start(tmp_path, cfg, client)
    assert events == []  # The existing code review still precedes execution.
    approve_fixture(root)
    result = run_full_pipeline(resume=root, client=client)
    assert result['status'] == 'completed' and result['actual_valid_nodes'] == 3
    assert events.index('M1') < events.index('edges_upward') < events.index('edges_downward') < events.index('edges_intrascale')
    graph = read_json(root/'stage1_graph.json')
    assert all('analysis_contract' in node for node in graph['nodes'])
    assert len(read_json(root/'final_causal_graph.json')['nodes']) == 3
    assert not (root/'internal/stage1/numeric_validation_request.json').exists()
    calls = list(client.calls)
    assert run_full_pipeline(resume=root,client=client)['status'] == 'completed'
    assert client.calls == calls
