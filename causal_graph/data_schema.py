"""Observed data contracts; no trajectory values enter model prompts."""
from copy import deepcopy
import json

import pyarrow as pa
from simulations.common.trajectory_api import Trajectory

from .io import object_digest

VERSION = '2.0'


def describe_json(value, depth=0):
    """Types and keys only. Sample array items explicitly; never serialize values."""
    if value is None:
        return {'types': ['null']}
    if isinstance(value, bool):
        return {'types': ['boolean']}
    if isinstance(value, (int, float)):
        return {'types': ['number']}
    if isinstance(value, str):
        return {'types': ['string']}
    if depth >= 16:
        return {'types': ['array' if isinstance(value, list) else 'object'], 'inspection_truncated': True}
    if isinstance(value, list):
        items = None
        for item in value[:8]:
            shape = describe_json(item, depth + 1)
            items = shape if items is None else merge_shapes(items, shape)
        return {'types': ['array'], 'items': items or {'types': [], 'unobserved': True}}
    # Numeric-key maps are agent identifiers rather than thousands of field names.
    if value and all(str(k).lstrip('-').isdecimal() for k in value):
        shapes = [describe_json(v, depth + 1) for v in list(value.values())[:8]]
        shape = shapes[0]
        for other in shapes[1:]:
            shape = merge_shapes(shape, other)
        return {'types': ['object'], 'key_pattern': 'integer_identifier', 'additional_properties': shape}
    return {'types': ['object'], 'properties': {k: describe_json(v, depth + 1) for k, v in value.items()}}


def merge_shapes(a, b, common=False):
    types = set(a['types']) & set(b['types']) if common else set(a['types']) | set(b['types'])
    result = {'types': sorted(types)}
    for key in ('items', 'additional_properties'):
        if key in a and key in b:
            result[key] = merge_shapes(a[key], b[key], common)
        elif not common and (key in a or key in b):
            result[key] = deepcopy(a.get(key, b.get(key)))
    if 'properties' in a or 'properties' in b:
        ap, bp = a.get('properties', {}), b.get('properties', {})
        keys = set(ap) & set(bp) if common else set(ap) | set(bp)
        properties = {}
        for key in sorted(keys):
            if key in ap and key in bp:
                shape = merge_shapes(ap[key], bp[key], common)
                if common and not shape['types']:
                    continue
            else:
                shape = deepcopy(ap.get(key, bp.get(key)))
            shape['may_be_absent'] = key not in ap or key not in bp or ap.get(key, {}).get('may_be_absent', False) or bp.get(key, {}).get('may_be_absent', False)
            properties[key] = shape
        result['properties'] = properties
    if a.get('key_pattern') == b.get('key_pattern') and a.get('key_pattern'):
        result['key_pattern'] = a['key_pattern']
    return result


def inspect_trajectory_schema(run):
    trajectory = Trajectory(run['directory'])
    tables = {}
    for name, catalog in trajectory.catalog.items():
        frame = trajectory.read(name)
        fields = {}
        for column, declared in catalog['fields'].items():
            series = frame[column]
            observed = series.dropna()
            actual_type = str(pa.array(observed).type) if len(observed) else declared.get('type', 'unknown')
            fields[column] = {'type': actual_type, 'catalog_type': declared.get('type', 'unknown'),
                              'description': declared.get('description') or 'unknown',
                              'allows_missing': True, 'nullability_source': 'public reader does not expose Parquet nullability; conservatively nullable',
                              'missing_observed': bool(series.isna().any()),
                              'type_observation': 'observed_nonnull_values' if len(observed) else 'catalog_only_no_nonnull_values'}
            if column.endswith('_json'):
                candidates = observed.tolist()
                positions = sorted({0, len(candidates) // 2, len(candidates) - 1}) if candidates else []
                shape = None
                errors = []
                for position in positions:
                    try:
                        current = describe_json(json.loads(candidates[position]))
                        shape = current if shape is None else merge_shapes(shape, current)
                    except (ValueError, TypeError):
                        errors.append('invalid_or_non_JSON_record')
                fields[column]['json_structure'] = shape
                fields[column]['json_inspection'] = {'records_inspected': len(positions), 'row_selection': 'first_middle_last_nonnull',
                    'array_items_per_level': 8, 'max_depth': 16, 'exhaustive': False, 'errors': errors,
                    'semantics': 'Nested names/types observed in sampled records; meanings unknown unless provided by catalog.'}
        tables[name] = {'purpose': catalog.get('granularity') or 'unknown',
                        'record_granularity': catalog.get('granularity') or 'unknown',
                        'time_coordinate': 'step', 'time_unit': 'platform update step',
                        'auxiliary_time_fields': {k: v['description'] for k, v in fields.items() if k in ('simulation_day', 'timestamp_or_sim_time')},
                        'agent_identifiers': {k: v['description'] for k, v in fields.items() if k in ('agent_id', 'partner_id', 'uid', 'target_id')},
                        'fields': fields}
    return {'schema_version': VERSION, 'tables': tables}


def schema_relationships(tables):
    relationships = []
    names = sorted(tables)
    for index, source in enumerate(names):
        for target in names[index + 1:]:
            keys = [k for k in ('run_id', 'step', 'agent_id') if k in tables[source]['fields'] and k in tables[target]['fields'] and
                    tables[source]['fields'][k]['type'] == tables[target]['fields'][k]['type']]
            if keys:
                relationships.append({'source_table': source, 'target_table': target, 'shared_keys': keys,
                                      'meaning': 'Available shared key names/types; verify join cardinality locally, not a causal relation.'})
    if 'agent_states' in tables and 'agent_id' in tables['agent_states']['fields']:
        for name, table in tables.items():
            for key in ('partner_id', 'target_id'):
                if key in table['fields']:
                    relationships.append({'source_table': name, 'source_field': key, 'target_table': 'agent_states',
                                          'target_field': 'agent_id', 'shared_keys': ['run_id', 'step'],
                                          'meaning': table['fields'][key]['description'],
                                          'constraint': 'Potential endpoint lookup only; null/sentinel/unmatched IDs require explicit handling.'})
    return relationships


def build_data_schema(runs):
    if not runs:
        raise ValueError('No input runs for data schema')
    schemas = [inspect_trajectory_schema(r) for r in runs]
    common_tables = set.intersection(*(set(s['tables']) for s in schemas))
    tables, differences = {}, []
    for name in sorted(set.union(*(set(s['tables']) for s in schemas))):
        if name not in common_tables:
            differences.append({'table': name, 'reason': 'not_recorded_in_every_run'})
            continue
        members = [s['tables'][name] for s in schemas]
        table = deepcopy(members[0])
        table['fields'] = {}
        for field in sorted(set.union(*(set(t['fields']) for t in members))):
            fields = [t['fields'].get(field) for t in members]
            if any(f is None for f in fields) or len({f['type'] for f in fields if f is not None}) != 1:
                differences.append({'table': name, 'field': field, 'reason': 'missing_or_type_mismatch',
                                    'run_types': {r['manifest']['run_id']: f['type'] if f else None for r, f in zip(runs, fields)}})
                continue
            common = deepcopy(fields[0])
            common['missing_observed'] = any(f['missing_observed'] for f in fields)
            if len({f['description'] for f in fields}) > 1:
                common['description'] = 'unknown: catalog descriptions differ across runs'
                differences.append({'table': name, 'field': field, 'reason': 'description_mismatch'})
            if 'json_structure' in common:
                if any(f.get('json_structure') is None for f in fields):
                    common['json_structure'] = None
                else:
                    for f in fields[1:]:
                        common['json_structure'] = merge_shapes(common['json_structure'], f['json_structure'], common=True)
                common['json_inspection']['records_inspected'] = sum(f['json_inspection']['records_inspected'] for f in fields)
                if len({object_digest(f.get('json_structure')) for f in fields}) > 1:
                    differences.append({'table': name, 'field': field, 'reason': 'nested_JSON_structures_differ_common_paths_only'})
            table['fields'][field] = common
        table['agent_identifiers'] = {k: v for k, v in table['agent_identifiers'].items() if k in table['fields']}
        tables[name] = table
    schema = {'schema_version': VERSION, 'scope': 'common_fields_of_all_input_runs',
              'tables': tables, 'relationships': schema_relationships(tables),
              'time_contract': 'Use platform step as output index; do not concatenate seeds. Auxiliary native dates are not necessarily observed event times.',
              'values_included': False}
    audit = {'per_run': {r['manifest']['run_id']: s for r, s in zip(runs, schemas)}, 'differences': differences,
             'schema_sha256': object_digest(schema)}
    return schema, audit
