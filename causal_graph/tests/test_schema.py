from copy import deepcopy

import pytest

from causal_graph.schemas import parse_response, validate_stage, code_errors
from .fixtures import fixture_outputs, fixture_context


@pytest.mark.parametrize('text', ['not json', '{"a":1,"a":2}', '{"value":NaN}', '```json\n{}'])
def test_invalid_json(text):
    with pytest.raises(ValueError):
        parse_response(text)


def test_code_fence():
    assert parse_response('```json\n{"ok":true}\n```') == {'ok': True}


@pytest.mark.parametrize('mutation,error', [('missing', 'required'), ('reference', 'Invalid node reference'),
    ('duplicate_node', 'Duplicate indicator_id'), ('duplicate_edge_id', 'Duplicate edge_id'),
    ('direction', 'scale direction'), ('self_loop', 'Self loop'), ('scale', 'not one of'), ('evidence', 'Additional properties')])
def test_semantic_constraints(settings, mutation, error):
    outputs = fixture_outputs()
    stage = 'edges_upward'
    if mutation == 'missing':
        del outputs[stage]['edges'][0]['semantic_rationale']
    elif mutation == 'reference':
        outputs[stage]['edges'][0]['source'] = 'missing'
    elif mutation == 'duplicate_node':
        stage = 'indicators'
        outputs[stage]['indicators'].append(deepcopy(outputs[stage]['indicators'][0]))
    elif mutation == 'duplicate_edge_id':
        outputs[stage]['edges'][1]['edge_id'] = outputs[stage]['edges'][0]['edge_id']
    elif mutation == 'direction':
        outputs[stage]['edges'][0].update(source='test_c', target='test_a')
    elif mutation == 'self_loop':
        outputs[stage]['edges'][0]['target'] = 'test_a'
    elif mutation == 'scale':
        stage = 'indicators'
        outputs[stage]['indicators'][0]['scale'] = 'nano'
    elif mutation == 'evidence':
        outputs[stage]['edges'][0]['p_value'] = .01
    context = fixture_context()
    context.update(outputs['phenomena'])
    context.update(outputs['indicators'])
    report = validate_stage(stage, outputs[stage], context, settings)
    assert not report['valid'] and error.lower() in ' '.join(report['errors']).lower()


@pytest.mark.parametrize('code', ['def compute_indicator(:\n pass',
    'def compute_indicator(x):\n return x', 'def compute_indicator(data, config):\n return 5',
    'import os\ndef compute_indicator(data, config):\n return data',
    'import numpy as np\ndef compute_indicator(data, config):\n return np.random.normal(len(data))'])
def test_invalid_code(code):
    assert code_errors(code)


def test_valid_generated_structure(settings):
    outputs = fixture_outputs()
    context = fixture_context(outputs)
    for stage in outputs:
        assert validate_stage(stage, outputs[stage], context, settings)['valid']
        if not stage.startswith('edges_'):context.update(outputs[stage])
