"""Scientific-interface tests with explicit synthetic observation fixtures, not live results."""
from copy import deepcopy
from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from causal_graph.config import PipelineConfig, load_pipeline
from causal_graph.prompts import build_messages
from causal_graph.schemas import validate_stage
from causal_graph.tests.fixtures import fixture_context
from causal_graph.trusted_worker import compute_reviewed
from causal_discovery.m1_data import adapt_graph
from full_pipeline.main import ROOT, load_config
from observation_contract import VERSION, m1_options, validate_contract
from causal_graph.indicator_runner import check_result


def contract(entity=True, features=None):
    features = features or ['value']
    return {'version': VERSION, 'observation_unit': 'agent' if entity else 'system',
        'entity_keys': ['agent_id'] if entity else [], 'time_coordinate': 'step',
        'sampling_interval_steps': 1, 'temporal_window_steps': 0, 'output_features': features,
        'output_dimension': len(features), 'analysis_dimension': len(features), 'missing_policy': 'Undefined observations stay NaN',
        'analysis_definition': 'Population mean of recorded per-agent values at each step; not an individual causal effect' if entity else 'Fixed observed feature vector at step t',
        'mapping': {'kind': 'entity_aggregate' if entity else 'feature_vector', 'aggregation': 'mean' if entity else None,
            'aggregation_missing': 'propagate' if entity else None, 'features': features, 'entity_ids': [], 'entity_id': None},
        'mechanism_scale_rationale': 'Mechanism layer is separately declared from the statistical observation unit'}


def test_research_default_and_small_protocol_are_distinct():
    config = load_config(); limits = load_pipeline(ROOT / config['stage1']['pipeline_config'])
    assert config['experiment_mode'] == 'research'
    assert limits.min_indicators_per_scale == 4 and limits.target_indicators_per_scale == 6
    assert limits.max_indicators == 30 and limits.require_analysis_contract
    small = load_config(ROOT / 'full_pipeline/examples/low_cost_acceptance.yaml')
    assert small['experiment_mode'] == 'interface_test' and small['stage1']['pipeline_overrides']['max_indicators'] == 3


def test_three_nodes_cannot_pass_formal_coverage_and_prompt_has_contract():
    context = fixture_context(); limits = load_pipeline(ROOT / 'causal_graph/configs/pipeline_research.yaml')
    nodes = deepcopy(context['indicators'])
    for node in nodes: node['analysis_contract'] = contract()
    report = validate_stage('indicators', {'indicators': nodes}, context, limits)
    assert not report['valid'] and all(any(scale in e and 'minimum 4' in e for e in report['errors']) for scale in ('micro','meso','macro'))
    payload = json.loads(build_messages('indicators', 'explicit mock', context, limits)[1]['content'])
    assert 'target 6 per scale' in payload['task'] and 'analysis_contract' in payload['output_schema']['properties']['indicators']['items']['required']
    assert 'Mechanism scale' in payload['task'] and 'predeclared' in payload['task']
    formats = payload['analysis_contract_format']
    assert formats['agent_or_group_scalar_analysis']['mapping']['features'] == ['value']
    assert formats['system_scalar_analysis']['entity_keys'] == []


def test_entity_requires_mapping_and_dimensions_cannot_be_silently_changed():
    raw = contract(); validate_contract(raw)
    assert m1_options(raw) == {'features':['value'], 'entity_mode':'aggregate', 'aggregation':'mean','aggregation_missing':'propagate'}
    bad = deepcopy(raw); bad['mapping']['kind'] = 'identity'; bad['mapping']['aggregation'] = None
    with pytest.raises(ValueError, match='Entity observations'): validate_contract(bad)
    bad = deepcopy(raw); bad['analysis_dimension'] = 2
    with pytest.raises(ValueError, match='dimensions'): validate_contract(bad)


def test_m1_applies_predeclared_mapping_without_entity_pseudoreplication(tmp_path):
    nodes = [{'node_id':'micro', 'indicator_id':'micro', 'scale':'micro', 'analysis_contract':contract()}]
    for rid in ('seed11','seed22'):
        values = pd.DataFrame([{'run_id':rid,'indicator_id':'micro','step':t,
            'entity_id':json.dumps({'agent_id':i}), 'feature':'value','value':float(t + 2*i)} for t in range(12) for i in range(3)])
        file = tmp_path / f'{rid}.parquet'; values.to_parquet(file,index=False)
        nodes[0].setdefault('execution',{})[rid] = {'status':'success','series_file':str(file)}
    graph = {'nodes':nodes,'edges':[],'run_ids':['seed11','seed22']}
    cfg = {'data':{'min_total_observations':8,'min_samples_per_run':4}, 'rnn':{'max_lag':1},
        'split':{'fractions':[.25,.25,.25,.25], 'min_windows':{'train':2,'validation':2,'confirmation':2,'test':2}}}
    data = adapt_graph(graph,cfg)
    assert data['valid_nodes'] == ['micro']
    for rid in graph['run_ids']:
        assert data['data_report']['micro']['runs'][rid]['rows'] == 12  # 36 entity observations are NOT 36 time samples.
        np.testing.assert_allclose(np.array(data['series']['micro'][rid]['values'])[:,0], np.arange(12)+2)
        assert data['transformations']['micro'][rid]['analysis_definition'] == nodes[0]['analysis_contract']['analysis_definition']
    bad = deepcopy(cfg); bad['data']['node_overrides'] = {'micro':{'aggregation':'sum'}}
    assert 'conflicts' in adapt_graph(graph,bad)['invalid_nodes']['micro']['reason']


def test_bounded_window_execution_matches_whole_run_without_boundary_loss():
    class Fixture:
        def __init__(self): self.requested = []
        def available_steps(self): return list(range(30))
        def read(self,name,start=None,end=None,columns=None):
            frame = pd.DataFrame({'step':range(30),'x':np.arange(30)**2,'unrelated':np.ones(30)})
            if start is not None: frame=frame.loc[frame.step.between(start,end)]
            self.requested.append((start,end,columns)); return frame.loc[:,columns].copy()
    def rolling(data,config):
        return data['agent_states'].set_index('step').x.rolling(4,min_periods=4).mean()
    observation = Fixture(); metadata = contract(False); metadata['temporal_window_steps'] = 3
    whole = compute_reviewed(observation,rolling,{'agent_states':['step','x']},{})
    batched = compute_reviewed(observation,rolling,{'agent_states':['step','x']},{},metadata,7)
    pd.testing.assert_series_equal(whole,batched)
    assert observation.requested[-1][1] == 29
    assert all(v[2] == ['step','x'] for v in observation.requested)


def test_declared_observed_population_mean_accepts_undefined_entities_but_not_fake_finite_data(tmp_path):
    index=pd.MultiIndex.from_product([range(12),[0,1]],names=['step','agent_id'])
    raw=pd.Series([v for t in range(12) for v in (np.nan,float(t))],index=index)
    settings=PipelineConfig(min_observations=1)
    with pytest.raises(ValueError,match='insufficient actual observations'):
        check_result(raw,'r','micro',range(12),settings)
    series,quality=check_result(raw,'r','micro',range(12),settings,allow_undefined_entities=True)
    assert quality['columns']['value']['entities_without_defined_values']==1
    file=tmp_path/'observations.parquet'; series.to_parquet(file,index=False)
    declared=contract(); declared['mapping']['aggregation_missing']='observed'
    graph={'nodes':[{'node_id':'micro','indicator_id':'micro','scale':'micro','analysis_contract':declared,
        'execution':{'r':{'status':'success','series_file':str(file)}}}],'edges':[],'run_ids':['r']}
    cfg={'data':{'min_total_observations':8,'min_samples_per_run':4},'rnn':{'max_lag':1},
         'split':{'fractions':[.25]*4,'min_windows':{'train':2,'validation':2,'confirmation':2,'test':2}}}
    data=adapt_graph(graph,cfg)
    assert data['valid_nodes']==['micro']
    np.testing.assert_array_equal(np.array(data['series']['micro']['r']['values'])[:,0],np.arange(12))
    assert set(data['transformations']['micro']['r']['contributing_entity_counts'].values())=={1}
    with pytest.raises(ValueError,match='insufficient actual observations'):
        check_result(raw*float('nan'),'r','micro',range(12),settings,allow_undefined_entities=True)


def test_graph_export_preserves_declared_analysis_object(tmp_path):
    from causal_graph.graph_export import assemble_graph, export_graphs
    context = fixture_context()
    for node in context['indicators']:
        node['analysis_contract'] = contract(False)
    graph = assemble_graph(context, 'explicit_fixture', tmp_path)
    reports = [{'run_id':'r', 'indicator_id':n['indicator_id'], 'status':'success',
                'series_file':'test-only.parquet', 'series_sha256':'a'*64} for n in graph['nodes']]
    exported = export_graphs(graph, reports, ['r'], tmp_path)
    assert len(exported['nodes']) == 3
    for original, node in zip(context['indicators'], exported['nodes']):
        assert node['analysis_contract'] == original['analysis_contract']
        assert node['mathematical_definition'] == original['mathematical_definition']
