from copy import deepcopy
import json

from causal_graph.data_schema import build_data_schema, describe_json
from causal_graph.inputs import inspect_run
from causal_graph.io import object_digest
from causal_graph.prompts import build_messages
from causal_graph.schemas import validate_stage
from causal_graph.code_contract import analyze_access
from .fixtures import fixture_context, fixture_outputs


def test_real_catalog_schema_no_values(small_run):
    run = inspect_run(small_run)
    schema, audit = build_data_schema([run])
    fields = schema['tables']['agent_states']['fields']
    assert {'step', 'agent_id', 'x', 'happy'} <= set(fields)
    assert fields['happy']['type'] == 'bool'
    assert fields['x']['description'] != 'unknown'
    assert audit['schema_sha256'] == object_digest(schema)
    assert schema['values_included'] is False
    shape = json.dumps(describe_json({'a': 123456.789, 'b': 'PRIVATE_LITERAL', 'agents': {'123456789': {'q': True}}}))
    assert 'PRIVATE_LITERAL' not in shape and '123456.789' not in shape and '123456789' not in shape
    assert 'integer_identifier' in shape


def test_common_fields_types_and_nested_differences(monkeypatch, small_run):
    from causal_graph.data_schema import inspect_trajectory_schema
    base = inspect_trajectory_schema(inspect_run(small_run))
    other = deepcopy(base)
    del other['tables']['agent_states']['fields']['x']
    other['tables']['agent_states']['fields']['y']['type'] = 'string'
    other['tables']['agent_states']['fields']['happy']['description'] = 'different meaning'
    monkeypatch.setattr('causal_graph.data_schema.inspect_trajectory_schema', lambda r: base if r['directory'] == 'a' else other)
    runs = [{'directory': d, 'manifest': {'run_id': d}} for d in ('a', 'b')]
    common, audit = build_data_schema(runs)
    fields = common['tables']['agent_states']['fields']
    assert 'x' not in fields and 'y' not in fields
    assert fields['happy']['description'].startswith('unknown')
    assert len(audit['differences']) == 3


def test_prompt_schema_boundary_and_edge_independence(settings):
    context = fixture_context()
    context['edges_upward'] = [{'secret_other_edges': 'MUST_NOT_ENTER_PROMPT'}]
    for stage in ('phenomena', 'indicators', 'codes', 'edges_upward', 'edges_downward', 'edges_intrascale'):
        user = json.loads(build_messages(stage, 'fixed scenario', context, settings)[1]['content'])
        if stage in ('indicators', 'codes'):
            assert user['data_schema'] == context['data_schema']
            assert user['data_schema_sha256'] == object_digest(context['data_schema'])
        else:
            assert 'data_schema' not in user
        assert 'MUST_NOT_ENTER_PROMPT' not in json.dumps(user)


def test_generated_field_contract_and_drift(settings):
    context = fixture_context()
    outputs = fixture_outputs()
    outputs['indicators']['indicators'][0]['required_data']['agent_states'].append('fake_field')
    assert not validate_stage('indicators', outputs['indicators'], context, settings)['valid']
    code = outputs['codes']['codes'][0]
    code['required']['agent_states'] = ['agent_id']
    report = validate_stage('codes', outputs['codes'], context, settings)
    assert not report['valid'] and 'undeclared fields' in str(report['errors'])
    assert any(w['type'] == 'required_data_changed' for w in report['warnings'])


def test_static_aliases_derived_columns_and_grouped_output():
    schema = fixture_context()['data_schema']
    schema['tables']['agent_states']['fields']['x'] = {'type': 'double'}
    code = '''def compute_indicator(data, config):
    df = data['agent_states'].copy()
    df['derived'] = df['x'] * 2
    grouped = df.groupby('step').agg(mean_derived=('derived', 'mean'))
    return grouped['mean_derived']
'''
    assert not analyze_access(code, {'agent_states': ['step', 'x']}, schema)['errors']
    wrong = code.replace("df['x']", "df['absent']")
    assert 'undeclared fields' in str(analyze_access(wrong, {'agent_states': ['step', 'x']}, schema)['errors'])
