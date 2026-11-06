"""Version 2 schemas: observed fields and cyclic three-direction candidate graphs."""
import ast
import json
import re
from jsonschema import Draft202012Validator
from .code_contract import check_required, analyze_access

VERSION = '2.0'
TEXT = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
ID = {'type': 'string', 'pattern': r'^[A-Za-z][A-Za-z0-9_-]{0,79}$'}

def obj(fields):
    return {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}

def array(items, minimum=1):
    return {'type':'array','items':items,'minItems':minimum}

REQUIRED = {'type':'object','additionalProperties':array(TEXT)}
PHENOMENON = obj({'phenomenon_id':ID,'name':TEXT,'description':TEXT})
INDICATOR = obj({'indicator_id':ID,'phenomenon_id':ID,'name':TEXT,
    'scale':{'enum':['micro','meso','macro']},'description':TEXT,
    'mathematical_definition':TEXT,'units':TEXT,'computation_notes':TEXT,
    'required_data':{**REQUIRED,'minProperties':1}})
CODE = obj({'indicator_id':ID,'required':REQUIRED,'config':{'type':'object'},
    'python_code':{'type':['string','null']},
    'implementation_status':{'enum':['implemented','unavailable']},
    'failure_reason':{'type':['string','null']}})
EDGE = obj({'edge_id':ID,'source':ID,'target':ID,
    'scale_direction':{'enum':['upward','downward','intra_scale']},
    'semantic_rationale':TEXT,'relation_type':{'const':'semantic_candidate'}})
EDGE_STAGES = {'edges_upward':'upward','edges_downward':'downward','edges_intrascale':'intra_scale'}
SCHEMAS = {'phenomena':obj({'phenomena':array(PHENOMENON)}),
    'indicators':obj({'indicators':array(INDICATOR)}),'codes':obj({'codes':array(CODE)})}
SCHEMAS.update({stage:obj({'edges':array(EDGE,0)}) for stage in EDGE_STAGES})
NODE = obj({**INDICATOR['properties'],**{k:v for k,v in CODE['properties'].items() if k!='indicator_id'},
    'node_id':ID,'code_file':{'type':['string','null']},'code_sha256':{'type':['string','null']},
    'generation_call':TEXT,'execution':{'type':'object'}})
GRAPH_EDGE = obj({**EDGE['properties'],'edge_id':TEXT,
    'source_phenomenon':ID,'target_phenomenon':ID,
    'generation_sources':array(obj({'stage':TEXT,'call':TEXT,'original_edge_id':ID,'row_index':{'type':'integer','minimum':0}}))})
GRAPH_SCHEMA = obj({'schema_version':{'const':VERSION},
    'evidence_status':{'const':'unvalidated_semantic_candidates'},
    'phenomena':array(PHENOMENON),'nodes':array(NODE),'edges':array(GRAPH_EDGE,0)})
EXECUTABLE_SCHEMA = obj({**GRAPH_SCHEMA['properties'],'nodes':array(NODE,0),
    'run_ids':array(TEXT),'execution_policy':{'const':'success_on_every_listed_run'},
    'excluded_nodes':array(obj({'indicator_id':ID,'run_status':{'type':'object',
        'additionalProperties':{'enum':['success','failed','not_executed']}}}),0),
    'excluded_edges':array(obj({'edge':GRAPH_EDGE,'reason':TEXT}),0)})

def classify_direction(source_scale, target_scale):
    rank = {'micro':0,'meso':1,'macro':2}
    delta = rank[target_scale]-rank[source_scale]
    return 'upward' if delta>0 else 'downward' if delta<0 else 'intra_scale'

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
    errors = [f'{"/".join(map(str,e.absolute_path))}: {e.message}'
              for e in Draft202012Validator(SCHEMAS[stage]).iter_errors(value)]
    warnings, contracts = [], {}
    if errors:
        return {'valid':False,'errors':errors,'warnings':warnings}
    entries = value['edges' if stage in EDGE_STAGES else stage]
    maximum = limits.max_edges//3 if stage in EDGE_STAGES else limits.max_phenomena if stage=='phenomena' else limits.max_indicators
    if len(entries)>maximum:
        errors.append(f'{stage} exceeds configured maximum {maximum}')
    id_key = 'edge_id' if stage in EDGE_STAGES else 'phenomenon_id' if stage=='phenomena' else 'indicator_id'
    ids = [v[id_key] for v in entries]
    if stage not in EDGE_STAGES and len(ids)!=len(set(ids)):
        errors.append(f'Duplicate {id_key}')
    if stage in ('phenomena','indicators'):
        names=[v['name'].strip().casefold() for v in entries]
        if len(names)!=len(set(names)): errors.append('Duplicate names')
    schema = context.get('data_schema')
    if stage in ('indicators','codes') and schema is None:
        errors.append('Observed data schema is required')
    if stage=='indicators':
        phenomena={v['phenomenon_id'] for v in context['phenomena']}
        if any(v['phenomenon_id'] not in phenomena for v in entries): errors.append('Invalid phenomenon reference')
        for pid in phenomena:
            if {v['scale'] for v in entries if v['phenomenon_id']==pid}!={'micro','meso','macro'}:
                errors.append(f'{pid}: each phenomenon requires all three scales')
        if schema:
            for item in entries:
                errors.extend(f'{item["indicator_id"]}: {e}' for e in check_required(item['required_data'],schema))
    if stage=='codes':
        definitions={v['indicator_id']:v for v in context['indicators']}
        if set(ids)!=set(definitions):errors.append('Code IDs must match all generated indicators exactly')
        for item in entries:
            iid=item['indicator_id']
            if item['implementation_status']=='unavailable':
                if not item['failure_reason'] or item['python_code'] is not None:
                    errors.append(f'{iid}: unavailable code needs a reason and null python_code')
                if schema: errors.extend(f'{iid}: {e}' for e in check_required(item['required'],schema))
                continue
            if item['failure_reason'] is not None or not item['required'] or not isinstance(item['python_code'],str):
                errors.append(f'{iid}: implemented code requires source, input fields and null failure_reason')
                continue
            syntax = code_errors(item['python_code'])
            errors.extend(f'{iid}: {e}' for e in syntax)
            if schema and not syntax:
                contract=analyze_access(item['python_code'],item['required'],schema)
                contracts[iid]=contract
                errors.extend(f'{iid}: {e}' for e in contract['errors'])
            if iid in definitions and item['required']!=definitions[iid]['required_data']:
                warnings.append({'indicator_id':iid,'type':'required_data_changed',
                    'definition_required':definitions[iid]['required_data'],'code_required':item['required']})
    if stage in EDGE_STAGES:
        nodes={v['indicator_id']:v for v in context['indicators']}
        pairs, by_id = set(), {}
        for edge in entries:
            source,target=edge['source'],edge['target']
            pair=(source,target)
            if edge['edge_id'] in by_id and by_id[edge['edge_id']]!=pair:
                errors.append('Duplicate edge_id refers to different endpoints')
            by_id[edge['edge_id']]=pair
            if pair in pairs:warnings.append({'type':'duplicate_edge','source':source,'target':target})
            pairs.add(pair)
            if source not in nodes or target not in nodes:
                errors.append(f'Invalid node reference: {source}->{target}')
                continue
            if source==target:errors.append(f'Self loop forbidden: {source}')
            actual=classify_direction(nodes[source]['scale'],nodes[target]['scale'])
            if edge['scale_direction']!=EDGE_STAGES[stage] or actual!=EDGE_STAGES[stage]:
                errors.append(f'Invalid scale direction: {source}->{target}')
    return {'valid':not errors,'errors':errors,'warnings':warnings,'code_contracts':contracts}
