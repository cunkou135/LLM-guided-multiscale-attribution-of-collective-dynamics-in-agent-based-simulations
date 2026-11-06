"""Portable JSON Schemas plus semantic/AST checks; never a security sandbox."""
import ast
import json
import re

from jsonschema import Draft202012Validator

TEXT = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
ID = {'type': 'string', 'pattern': r'^[A-Za-z][A-Za-z0-9_-]{0,79}$'}


def obj(fields):
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}


def array(items, minimum=1):
    return {'type': 'array', 'items': items, 'minItems': minimum}


PHENOMENON = obj({'phenomenon_id': ID, 'name': TEXT, 'description': TEXT})
INDICATOR = obj({'indicator_id': ID, 'phenomenon_id': ID, 'name': TEXT,
                 'scale': {'enum': ['micro', 'meso', 'macro']}, 'description': TEXT,
                 'mathematical_definition': TEXT, 'units': TEXT, 'computation_notes': TEXT})
CODE = obj({'indicator_id': ID, 'required': {'type': 'object', 'minProperties': 1,
             'propertyNames': {'enum': ['agent_states', 'events', 'contacts', 'raw_frames', 'model_states']},
             'additionalProperties': array(TEXT)}, 'config': {'type': 'object'}, 'python_code': TEXT})
EDGE = obj({'edge_id': ID, 'source': ID, 'target': ID, 'semantic_rationale': TEXT,
            'relation_type': {'const': 'semantic_candidate'}})
SCHEMAS = {'phenomena': obj({'phenomena': array(PHENOMENON)}),
           'indicators': obj({'indicators': array(INDICATOR)}),
           'codes': obj({'codes': array(CODE)}), 'edges': obj({'edges': array(EDGE)})}
GRAPH_SCHEMA = obj({'schema_version': {'const': '1.0'}, 'evidence_status': {'const': 'unvalidated_semantic_candidates'},
                    'phenomena': array(PHENOMENON), 'nodes': array(obj({**INDICATOR['properties'],
                    'node_id': ID, 'required': CODE['properties']['required'], 'config': {'type': 'object'},
                    'python_code': TEXT, 'code_file': TEXT, 'code_sha256': TEXT, 'generation_call': TEXT})),
                    'edges': array(EDGE)})
EXECUTABLE_SCHEMA = obj({**GRAPH_SCHEMA['properties'],
    'nodes': array(GRAPH_SCHEMA['properties']['nodes']['items'], 0), 'edges': array(EDGE, 0),
    'run_ids': array(TEXT), 'execution_policy': {'const': 'success_on_every_listed_run'},
    'excluded_nodes': array(obj({'indicator_id': ID, 'run_status': {'type': 'object',
        'additionalProperties': {'enum': ['success', 'failed', 'not_executed']}}}), 0),
    'excluded_edges': array(obj({'edge': EDGE, 'reason': TEXT}), 0),
    'nodes_without_complete_path': array(ID, 0)})


def parse_response(text):
    text = text.strip()
    if text.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```', text, flags=re.S)
        if not match:
            raise ValueError('Malformed JSON code fence')
        text = match.group(1)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    def reject(value):
        raise ValueError(f'Non-finite JSON value: {value}')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=reject)


def code_errors(code):
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f'Python syntax: {exc}']
    errors = []
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'compute_indicator']
    if len(functions) != 1:
        return ['Exactly one compute_indicator function is required']
    fn = functions[0]
    if ([a.arg for a in fn.args.args] != ['data', 'config'] or fn.args.posonlyargs or
            fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg or fn.args.defaults or fn.decorator_list):
        errors.append('Signature must be def compute_indicator(data, config) without decorators/defaults')
    if not any(isinstance(n, ast.Name) and n.id == 'data' and isinstance(n.ctx, ast.Load) for n in ast.walk(fn)):
        errors.append('Function must read data; constant-only observations are forbidden')
    allowed_imports = {'numpy', 'pandas', 'scipy', 'math', 'statistics', 'collections', 'itertools', 'json'}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            roots = [a.name.split('.')[0] for a in n.names] if isinstance(n, ast.Import) else [(n.module or '').split('.')[0]]
            if (set(roots) - allowed_imports or (isinstance(n, ast.ImportFrom) and n.level) or
                    (isinstance(n, ast.ImportFrom) and 'random' in (n.module or '').split('.')) or
                    any(a.name in {'random', 'default_rng', 'RandomState'} for a in n.names)):
                errors.append('Only documented scientific/utility imports are permitted')
        if isinstance(n, ast.Attribute) and (n.attr.startswith('__') or n.attr in {'random', 'rvs', 'default_rng', 'RandomState', 'to_csv', 'to_pickle', 'to_parquet', 'read_csv', 'read_parquet', 'read_pickle'}):
            errors.append(f'Forbidden generated-code attribute: {n.attr}')
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {'exec', 'eval', 'open', 'compile', '__import__', 'input'}:
            errors.append(f'Forbidden generated-code call: {n.func.id}')
    for n in tree.body:
        if not isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef)) and not (
                isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)):
            errors.append('Top-level code may contain only imports, docstring and functions')
    return sorted(set(errors))


def validate_stage(stage, value, context, limits):
    errors = [f'{"/".join(map(str, e.absolute_path))}: {e.message}'
              for e in Draft202012Validator(SCHEMAS[stage]).iter_errors(value)]
    if errors:
        return {'valid': False, 'errors': errors}
    entries = value[stage]
    max_count = {'phenomena': limits.max_phenomena, 'indicators': limits.max_indicators,
                 'codes': limits.max_indicators, 'edges': limits.max_edges}[stage]
    if len(entries) > max_count:
        errors.append(f'{stage} exceeds configured maximum {max_count}')
    id_key = {'phenomena': 'phenomenon_id', 'indicators': 'indicator_id', 'codes': 'indicator_id', 'edges': 'edge_id'}[stage]
    ids = [v[id_key] for v in entries]
    if len(ids) != len(set(ids)):
        errors.append(f'Duplicate {id_key}')
    if stage in ('phenomena', 'indicators'):
        names = [v['name'].strip().casefold() for v in entries]
        if len(names) != len(set(names)):
            errors.append('Duplicate names')
    if stage == 'indicators':
        phenomena = {v['phenomenon_id'] for v in context['phenomena']}
        if any(v['phenomenon_id'] not in phenomena for v in entries):
            errors.append('Invalid phenomenon reference')
        for pid in phenomena:
            if {v['scale'] for v in entries if v['phenomenon_id'] == pid} != {'micro', 'meso', 'macro'}:
                errors.append(f'{pid}: each phenomenon requires all three scales')
    if stage == 'codes':
        if set(ids) != {v['indicator_id'] for v in context['indicators']}:
            errors.append('Code IDs must match all generated indicators exactly')
        for code in entries:
            errors.extend(f'{code["indicator_id"]}: {e}' for e in code_errors(code['python_code']))
    if stage == 'edges':
        nodes = {v['indicator_id']: v for v in context['indicators']}
        pairs = set()
        for edge in entries:
            s, t = edge['source'], edge['target']
            if (s, t) in pairs:
                errors.append(f'Duplicate edge endpoints: {s}->{t}')
            pairs.add((s, t))
            if s not in nodes or t not in nodes:
                errors.append(f'Invalid node reference: {s}->{t}')
                continue
            if (nodes[s]['scale'], nodes[t]['scale']) not in {('micro', 'meso'), ('meso', 'macro')}:
                errors.append(f'Invalid scale direction: {s}->{t}')
            if nodes[s]['phenomenon_id'] != nodes[t]['phenomenon_id']:
                errors.append(f'Cross-phenomenon edge is outside T_e: {s}->{t}')
        # Every generated node participates in a complete micro -> meso -> macro path.
        covered = set()
        for s, middle in pairs:
            if s in nodes and middle in nodes and nodes[s]['scale'] == 'micro' and nodes[middle]['scale'] == 'meso':
                for m, t in pairs:
                    if m == middle and t in nodes and nodes[t]['scale'] == 'macro':
                        covered.update((s, middle, t))
        for nid in set(nodes) - covered:
            errors.append(f'Node {nid} lacks a complete phenomenon-linked cross-scale path')
    return {'valid': not errors, 'errors': errors}
