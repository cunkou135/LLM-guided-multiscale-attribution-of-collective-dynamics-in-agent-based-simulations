"""Extra integration checks and explicit scientific review binding; no code sandbox."""
import ast
from copy import deepcopy
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from causal_graph.indicator_runner import load_approvals
from causal_graph.io import digest, object_digest, read_json, save_json
from causal_graph.schemas import EXECUTABLE_SCHEMA, validate_stage
from causal_discovery.m5_graph import validate_final_graph
from .stage_manager import QualityError

REVIEW_CHECKS = ('syntax', 'fields', 'mathematical_definition', 'observation_unit', 'time_index', 'allowed_operations')


def issue(stage, kind, message, item=None):
    return {'stage': stage, 'type': kind, 'item_id': item, 'message': str(message)}


def classify_error(stage, message):
    text = str(message).lower()
    if any(v in text for v in ('json', 'expecting value', 'code fence', 'delimiter')): return 'invalid_json'
    if any(v in text for v in ('syntax', 'signature', 'forbidden', 'top-level', 'import')): return 'invalid_code'
    if any(v in text for v in ('field', 'table absent', 'column', 'required_data')): return 'field_reference'
    if 'duplicate' in text: return 'duplicate_variable' if stage == 'indicators' else 'result_integrity'
    if 'direction' in text: return 'relation_direction'
    if 'reference' in text: return 'node_reference'
    return 'incomplete_definition' if stage == 'indicators' else 'invalid_schema'


def check_generation(stage: str, value: dict, context: dict, limits) -> dict:
    report = validate_stage(stage, value, context, limits)
    problems = [issue(stage, classify_error(stage, e), e) for e in report['errors']]
    if stage == 'indicators':
        signatures = {}
        for node in value.get('indicators', []):
            formula = node.get('mathematical_definition', '').casefold()
            formula = re.sub(r'^\s*[^=]{1,50}=(?!=)', '', formula)
            formula = re.sub(r'\s+|[，。；,;]', '', formula)
            if formula in signatures:
                problems.append(issue(stage, 'duplicate_variable', f'Duplicate normalized mathematical definition of {signatures[formula]}', node['indicator_id']))
            signatures[formula] = node['indicator_id']
            for field in ('mathematical_definition', 'units', 'computation_notes'):
                if not node.get(field, '').strip(): problems.append(issue(stage, 'incomplete_definition', f'Missing {field}', node['indicator_id']))
    if stage == 'phenomena':
        descriptions = [p['description'].strip().casefold() for p in value.get('phenomena', [])]
        if len(descriptions) != len(set(descriptions)):
            problems.append(issue(stage, 'result_integrity', 'Repeated phenomenon description'))
    if stage == 'codes':
        forbidden = {'read_json', 'read_html', 'read_excel', 'read_sql', 'read_hdf', 'read_feather', 'load', 'save',
                     'savez', 'fromfile', 'tofile', 'to_json', 'to_excel', 'to_hdf', 'to_sql', 'system', 'popen'}
        for node in value.get('codes', []):
            if node.get('python_code'):
                try:
                    for entry in ast.walk(ast.parse(node['python_code'])):
                        if isinstance(entry, ast.Attribute) and entry.attr in forbidden:
                            problems.append(issue(stage, 'invalid_code', f'Unpermitted I/O/process attribute {entry.attr}', node['indicator_id']))
                except SyntaxError:
                    pass  # The existing syntax validator reports this with its precise line.
    report.update(issues=problems, valid=not problems,
                  scope='Static structural/field checks only; mathematical equivalence and execution permission require a separate review')
    if problems: raise QualityError(problems)
    return report


def definition_hash(node: dict) -> str:
    return object_digest({k: node[k] for k in ('indicator_id', 'phenomenon_id', 'scale', 'name', 'description',
        'mathematical_definition', 'units', 'computation_notes', 'required_data')})


def reviewed_approvals(graph: dict, review_file: Path, output: Path) -> tuple[dict | None, list]:
    """Require declared review of code AND unchanged definitions; never infer human approval."""
    review = read_json(review_file) if review_file.is_file() else {}
    pending, accepted, rejections = [], {}, {}
    for node in graph['nodes']:
        if node['implementation_status'] != 'implemented': continue
        iid = node['indicator_id']; record = review.get('reviews', {}).get(iid, {})
        matching = record.get('code_sha256') == node['code_sha256'] and record.get('definition_sha256') == definition_hash(node)
        if matching and record.get('verdict') == 'rejected':
            rejections[iid] = {'reason': record.get('reason', 'Explicit scientific/code review rejection'), 'code_sha256': node['code_sha256']}
        elif matching and record.get('verdict') == 'approved' and all(record.get('checks', {}).get(k) is True for k in REVIEW_CHECKS):
            accepted[iid] = node['code_sha256']
        else:
            pending.append({'indicator_id': iid, 'code_sha256': node['code_sha256'], 'definition_sha256': definition_hash(node),
                            'definition': {k: v for k, v in node.items() if k not in ('execution',)},
                            'required_review_checks': list(REVIEW_CHECKS)})
    save_json(output / 'review_request.json', {'review_file': str(review_file), 'pending': pending,
        'explicit_rejections': rejections, 'scope': 'Separate actual scientific/code review required; static validation is NOT approval or a sandbox'})
    if pending: return None, pending
    if accepted or rejections:
        basic = {k: review.get(k) for k in ('reviewer', 'reviewed_at', 'notes')}
        basic.update(code_sha256=accepted, rejections=rejections)
        snapshot = output / 'reviews' / (object_digest(review) + '.json')
        save_json(snapshot, review)
        compatible = snapshot.with_name(snapshot.stem + '_trusted_reviewed.json')
        save_json(compatible, basic)
        return load_approvals(compatible), []
    return None, []


def validate_stage1(graph: dict):
    core = {k: v for k, v in graph.items() if k in EXECUTABLE_SCHEMA['properties']}
    Draft202012Validator(EXECUTABLE_SCHEMA).validate(core)
    ids = {n['node_id'] for n in graph['nodes']}
    if len(ids) != len(graph['nodes']): raise ValueError('Duplicate stage1 node IDs')
    for node in graph['nodes']:
        if not set(graph['run_ids']) <= set(node['execution']): raise ValueError('Missing node/run execution')
        for rid in graph['run_ids']:
            result = node['execution'][rid]
            if result['status'] != 'success' or digest(result['series_file']) != result['series_sha256']:
                raise ValueError('Stage1 contains uncomputed or changed observations')
    if any(e['source'] not in ids or e['target'] not in ids for e in graph['edges']): raise ValueError('Dangling stage1 edge')


def validate_stage2(graph: dict, stage1: dict, audit: Path):
    validate_final_graph(graph)
    original = {n['node_id']: n for n in stage1['nodes']}
    data = read_json(audit / 'm1_data.json')
    if {n['node_id'] for n in graph['nodes']} != set(data['valid_nodes']): raise ValueError('Final node set differs from M1 admission')
    lags = {r['target']: r for r in read_json(audit / 'm2_lag_results.json')}
    candidates = {(e['source'], e['target']): e for e in stage1['edges']}
    for node in graph['nodes']:
        if node['mathematical_definition'] != original[node['node_id']]['mathematical_definition']:
            raise ValueError('Scientific node definition changed')
    for edge in graph['edges']:
        a, b = edge['source'], edge['target']; selected = lags[b]
        if a == b:
            supported = [v['lag'] for v in selected['self_evidence'] if v['status'] == 'supported']
            if edge['weight'] not in supported: raise ValueError('Unsupported self-memory weight')
        elif (a, b) not in candidates or edge['edge_id'] != candidates[(a, b)]['edge_id'] or edge['weight'] != selected['primary_lags'].get(a):
            raise ValueError('External edge ID or weight lacks candidate/M2 provenance')
        for evidence in edge['evidence']:
            keys = ('joint_calibration', 'synergy_calibration') if evidence['kind'] == 'pid_joint' else ('calibration',)
            for key in keys:
                if evidence.get(key, {}).get('p_value_valid') is not True:
                    raise ValueError('Accepted edge without calibrated numerical evidence')
            qkeys = ('joint_adjusted_p_value', 'synergy_adjusted_p_value') if evidence['kind'] == 'pid_joint' else ('adjusted_p_value',)
            alpha = read_json(audit / 'parameters.json')['decision']['alpha']
            if any(not isinstance(evidence.get(k), (int, float)) or evidence[k] > alpha for k in qkeys):
                raise ValueError('Accepted evidence fails configured decision threshold')
