"""Shared declarative observation/analysis interface; no discovery or simulation algorithm."""
from copy import deepcopy

from jsonschema import Draft202012Validator

VERSION = 'observation-analysis/1.0'
TEXT = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
STRINGS = {'type': 'array', 'items': TEXT, 'uniqueItems': True}
MAPPING = {'type': 'object', 'additionalProperties': False,
    'required': ['kind', 'aggregation', 'aggregation_missing', 'features', 'entity_ids', 'entity_id'],
    'properties': {'kind': {'enum': ['identity', 'entity_aggregate', 'entity_select', 'entity_vector', 'feature_vector']},
        'aggregation': {'enum': [None, 'mean', 'median', 'sum']},
        'aggregation_missing': {'enum': [None, 'propagate', 'observed']}, 'features': {**STRINGS, 'minItems': 1, 'maxItems': 4},
        'entity_ids': {'type': 'array', 'uniqueItems': True, 'items': {'type': ['integer', 'string', 'object']}},
        'entity_id': {'type': ['null', 'integer', 'string', 'object']}}}
SCHEMA = {'type': 'object', 'additionalProperties': False,
    'required': ['version', 'observation_unit', 'entity_keys', 'time_coordinate', 'sampling_interval_steps', 'temporal_window_steps',
                 'output_features', 'output_dimension', 'analysis_dimension', 'missing_policy', 'analysis_definition', 'mapping', 'mechanism_scale_rationale'],
    'properties': {'version': {'const': VERSION},
        'observation_unit': {'enum': ['agent', 'event', 'derived_group', 'system']},
        'entity_keys': STRINGS, 'time_coordinate': {'const': 'step'},
        'sampling_interval_steps': {'type': 'integer', 'minimum': 1},
        'temporal_window_steps': {'type': 'integer', 'minimum': 0, 'maximum': 1000},
        'output_features': {**STRINGS, 'minItems': 1, 'maxItems': 4}, 'missing_policy': TEXT,
        'output_dimension': {'type': 'integer', 'minimum': 1, 'maximum': 4},
        'analysis_dimension': {'type': 'integer', 'minimum': 1, 'maximum': 16},
        'analysis_definition': TEXT, 'mapping': MAPPING, 'mechanism_scale_rationale': TEXT}}


def validate_contract(contract: dict) -> dict:
    """Validate a mapping selected BEFORE inference; never infer an aggregation."""
    errors = list(Draft202012Validator(SCHEMA).iter_errors(contract))
    if errors: raise ValueError('; '.join(e.message for e in errors))
    mapping = contract['mapping']; kind = mapping['kind']; keys = contract['entity_keys']
    if not set(mapping['features']) <= set(contract['output_features']):
        raise ValueError('Analysis features must be explicitly declared output features')
    entity = contract['observation_unit'] != 'system'
    if entity != bool(keys): raise ValueError('Entity observations require explicit entity keys; system observations have none')
    if entity and kind in ('identity', 'feature_vector'):
        raise ValueError('Entity observations need an explicit aggregate/select/vector analysis mapping')
    if not entity and kind not in ('identity', 'feature_vector'):
        raise ValueError('System observations cannot use an entity mapping')
    if kind == 'identity' and len(mapping['features']) != 1:
        raise ValueError('Scalar identity requires exactly one selected feature')
    if kind == 'entity_aggregate' and mapping['aggregation'] is None:
        raise ValueError('Entity aggregation must have an explicit mathematical operator')
    if kind != 'entity_aggregate' and mapping['aggregation'] is not None:
        raise ValueError('Aggregation is only allowed for entity_aggregate')
    if (kind == 'entity_aggregate') != (mapping['aggregation_missing'] is not None):
        raise ValueError('Entity aggregation requires an explicit missing-data rule; other mappings use null')
    if kind == 'entity_select' and mapping['entity_id'] is None:
        raise ValueError('Entity selection requires an explicitly fixed entity_id')
    if kind == 'entity_vector' and not mapping['entity_ids']:
        raise ValueError('Entity vector requires an explicitly fixed ordered entity set')
    expected = len(mapping['features']) * (len(mapping['entity_ids']) if kind == 'entity_vector' else 1)
    if contract['output_dimension'] != len(contract['output_features']) or contract['analysis_dimension'] != expected:
        raise ValueError('Declared raw/analysis dimensions differ from the explicit mapping')
    return contract


def m1_options(contract: dict) -> dict:
    validate_contract(contract)
    mapping = contract['mapping']; kind = mapping['kind']
    options = {'features': deepcopy(mapping['features'])}
    if kind == 'entity_aggregate':
        options.update(entity_mode='aggregate', aggregation=mapping['aggregation'], aggregation_missing=mapping['aggregation_missing'])
    elif kind == 'entity_select':
        options.update(entity_mode='select', entity_id=deepcopy(mapping['entity_id']))
    elif kind == 'entity_vector':
        options.update(entity_mode='features', entity_ids=deepcopy(mapping['entity_ids']))
    return options
