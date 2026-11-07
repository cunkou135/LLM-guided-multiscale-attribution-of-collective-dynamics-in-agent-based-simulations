"""M5: fixed evidence rules, multiplicity control and one complete final graph."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Mapping

import numpy as np
from jsonschema import Draft202012Validator

from ._common import emit, read_json, save_json, serializable, settings


def adjust_pvalues(records: Mapping[str, Mapping], *, method: str = 'by', alpha: float = .05) -> dict:
    """Adjust only actual finite p-values explicitly marked calibrated; missing remains missing."""
    if method not in ('by', 'bh', 'none'): raise ValueError('Correction must be by, bh or none')
    valid, excluded = [], {}
    for key, record in records.items():
        p = record.get('p_value')
        if record.get('p_value_valid') is True and isinstance(p, (int, float)) and not isinstance(p, bool) and np.isfinite(p) and 0 <= p <= 1:
            valid.append((key, float(p)))
        else: excluded[key] = {'p_value': None, 'adjusted_p_value': None, 'reason': 'no valid calibrated p-value; never imputed'}
    valid.sort(key=lambda v: (v[1], v[0])); m = len(valid)
    factor = float(sum(1 / k for k in range(1, m + 1))) if method == 'by' else 1.0
    result, bound = {}, 1.0
    for rank in range(m, 0, -1):
        key, p = valid[rank - 1]
        q = p if method == 'none' else min(bound, p * m * factor / rank, 1.0)
        bound = q
        result[key] = {'p_value': p, 'adjusted_p_value': q, 'accepted': q <= alpha}
    return {'method': method, 'alpha': alpha, 'tested_count': m, 'hypotheses': result, 'excluded': excluded,
            'assumptions': 'BY permits arbitrary dependence; BH requires independence/positive dependence of valid p-values; component calibration assumptions still apply'}


def validate_final_graph(graph: Mapping) -> None:
    Draft202012Validator(read_json(Path(__file__).with_name('final_graph.schema.json'))).validate(graph)
    ids = [n['node_id'] for n in graph['nodes']]; edge_ids = [e['edge_id'] for e in graph['edges']]
    if len(ids) != len(set(ids)) or len(edge_ids) != len(set(edge_ids)): raise ValueError('Duplicate final IDs')
    if any(n['indicator_id'] != n['node_id'] for n in graph['nodes']): raise ValueError('Node/indicator ID mismatch')
    endpoints = set(); groups = {}
    for edge in graph['edges']:
        pair = (edge['source'], edge['target'])
        if not set(pair) <= set(ids): raise ValueError('Dangling edge')
        if pair in endpoints: raise ValueError('Duplicate endpoint pair; use multiple evidence records')
        endpoints.add(pair)
        if edge['weight'] not in edge['lags']: raise ValueError('Primary lag missing from actual lag candidates')
        if (edge['source'] == edge['target']) != (edge['relation_type'] == 'self_memory'):
            raise ValueError('Self memory must be explicitly distinguished')
        joint = [v for v in edge['evidence'] if v['kind'] == 'pid_joint']
        individual = [v for v in edge['evidence'] if v['kind'] in ('granger', 'pid_marginal')]
        if edge['relation_type'] == 'joint_only' and (not joint or individual):
            raise ValueError('joint_only must not claim independent member evidence')
        if edge.get('joint_group_id') and not any(v.get('joint_group_id') == edge['joint_group_id'] for v in joint):
            raise ValueError('Joint marker lacks actual joint evidence')
        for evidence in joint:
            if not {'joint_group_id', 'joint_sources', 'primary_lags'} <= set(evidence):
                raise ValueError('Incomplete joint metadata')
            group = groups.setdefault(evidence['joint_group_id'], {'sources': set(evidence['joint_sources']), 'target': edge['target'], 'members': set()})
            if group['sources'] != set(evidence['joint_sources']) or group['target'] != edge['target']:
                raise ValueError('Inconsistent joint group')
            if edge['source'] not in group['sources'] or not group['sources'] <= set(ids): raise ValueError('Invalid joint source')
            if evidence['primary_lags'][edge['source']] != edge['weight']: raise ValueError('Joint member lag mismatch')
            group['members'].add(edge['source'])
    for group in groups.values():
        if group['members'] != group['sources']: raise ValueError('Incomplete joint relationship')


def integrate_graph(graph: Mapping, data: Mapping, lag_results: list[Mapping], granger_results: list[Mapping],
                    pid_results: list[Mapping], config: Mapping | str | Path | None = None) -> dict:
    """Retain valid isolated nodes, accepted original external edges and confirmed temporal self edges."""
    cfg = settings(config); valid = set(data['valid_nodes'])
    original_nodes = {n.get('node_id', n.get('indicator_id')): n for n in graph['nodes']}
    if not valid <= set(original_nodes): raise ValueError('Data adapter cannot add nodes')
    candidates, parents = {}, {i: set() for i in valid}
    for edge in graph['edges']:
        a, b = edge['source'], edge['target']
        if a in valid and b in valid and a != b:
            candidates.setdefault((a, b), []).append(edge); parents[b].add(a)
    lags = {r['target']: r for r in lag_results}
    tests = {}
    for r in granger_results: tests[f'g:{r["source"]}:{r["target"]}'] = r.get('calibration', {})
    for r in lag_results:
        for evidence in r.get('self_evidence', []): tests[f's:{r["target"]}:{evidence["lag"]}'] = evidence.get('calibration', {})
    for index, r in enumerate(pid_results):
        for name, item in r.get('tests', {}).items(): tests[f'p:{index}:{name}'] = item.get('calibration', {})
    correction = adjust_pvalues(tests, method=cfg['decision']['correction'], alpha=cfg['decision']['alpha'])
    decisions, accepted = [], {}
    def passed(key, record):
        return record.get('status') == 'supported' and correction['hypotheses'].get(key, {}).get('accepted', False)
    def lag_list(value):
        return [value] if type(value) is int else list(value) if isinstance(value, (list, tuple)) else []
    def at_least(value, minimum):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and np.isfinite(value) and value >= minimum
    def lag_values(source, target):
        record = lags.get(target, {})
        values = lag_list(record.get('parent_lags', {}).get(source, []))
        primary = record.get('primary_lags', {}).get(source)
        if (record.get('parent_status', {}).get(source, record.get('status')) != 'estimated' or primary not in values or
                len(values) != len(set(values)) or
                any(type(v) is not int or v <= 0 for v in values)):
            return None
        return list(values), primary
    def add(source, target, method, evidence):
        values = lag_values(source, target)
        if values is None or (source, target) not in candidates: return False
        if (source, target) not in accepted:
            originals = candidates[(source, target)]; base = deepcopy(originals[0])
            base.update(candidate_relation_type=base.get('relation_type'), candidate_edge_ids=[e['edge_id'] for e in originals],
                        weight=values[1], lags=values[0], relation_type='joint_only', method=method, status='accepted', evidence=[])
            accepted[(source, target)] = base
        accepted[(source, target)]['evidence'].append(evidence)
        if evidence['kind'] != 'pid_joint': accepted[(source, target)]['relation_type'] = 'individual_predictive'
        return True
    for r in granger_results:
        a, b = r['source'], r['target']; key = f'g:{a}:{b}'
        values = lag_values(a, b)
        okay = (b in valid and len(parents.get(b, [])) == 1 and a in parents[b] and values is not None and
                r.get('primary_lag') == values[1] and set(r.get('lags', [])) == set(values[0]) and
                passed(key, r) and at_least(r.get('prediction_gain'), cfg['granger']['min_prediction_gain']))
        if okay:
            add(a, b, 'rnn_granger', {'kind': 'granger', 'method': 'rnn_granger', 'status': 'accepted',
                'prediction_gain': r['prediction_gain'], 'calibration': deepcopy(r['calibration']),
                'adjusted_p_value': correction['hypotheses'][key]['adjusted_p_value'], 'lags_origin': 'M2 held-out ablation'})
        decisions.append({'method': 'rnn_granger', 'source': a, 'target': b, 'accepted': bool(okay),
                          'upstream_reason': r.get('reason'), 'calibration_reason': r.get('calibration', {}).get('reason'),
                          'upstream_status': r.get('status'), 'reason': 'passed predeclared route, lag, gain and multiplicity rules' if okay else
                          'unsupported/inconclusive/calibration/lag/route condition; nonacceptance does not establish absence'})
    for index, r in enumerate(pid_results):
        sources, target = r['sources'], r['target']
        if len(sources) != 2 or target not in valid or len(parents.get(target, [])) < 2:
            decisions.append({'method': 'lagged_mmi_pid', 'target': target, 'accepted': False, 'reason': 'invalid pair, removed node or route mismatch'}); continue
        for number, source in enumerate(sources, 1):
            key = f'p:{index}:marginal_{number}'; record = r.get('tests', {}).get(f'marginal_{number}', {})
            values = lag_values(source, target)
            if (source in parents[target] and values is not None and set(values[0]) == set(lag_list(r.get('source_lags', {}).get(source))) and
                    passed(key, record) and at_least(record.get('gain_bits'), cfg['pid']['min_information_bits'])):
                add(source, target, 'lagged_mmi_pid', {'kind': 'pid_marginal', 'method': 'lagged_mmi_pid', 'status': 'accepted',
                    'pair_sources': sources, 'conditional_information_bits': r.get(f'i{number}'), 'redundancy_bits': r.get('redundancy'),
                    'unique_information_bits': r.get('unique', {}).get(source), 'predictive_gain_bits': record['gain_bits'],
                    'calibration': record['calibration'], 'adjusted_p_value': correction['hypotheses'][key]['adjusted_p_value'],
                    'interpretation': 'marginal predictive information; zero MMI unique is not a deletion rule'})
        joint_key, synergy_key = f'p:{index}:joint', f'p:{index}:synergy'
        joint, synergy = (r.get('tests', {}).get(k, {}) for k in ('joint', 'synergy'))
        complete = all(s in valid and s in parents[target] and lag_values(s, target) is not None and
                       set(lag_values(s, target)[0]) == set(lag_list(r.get('source_lags', {}).get(s))) for s in sources)
        okay = (complete and passed(joint_key, joint) and passed(synergy_key, synergy) and
                at_least(r.get('synergy'), cfg['pid']['min_information_bits']) and
                at_least(joint.get('gain_bits'), cfg['pid']['min_information_bits']) and
                at_least(synergy.get('gain_bits'), cfg['pid']['min_information_bits']))
        if okay:
            group = 'J_' + hashlib.sha256((target + ':' + ':'.join(sorted(sources))).encode()).hexdigest()[:16]
            primaries = {s: lag_values(s, target)[1] for s in sources}
            for source in sources:
                add(source, target, 'lagged_mmi_pid', {'kind': 'pid_joint', 'method': 'lagged_mmi_pid', 'status': 'accepted',
                    'joint_group_id': group, 'joint_sources': sorted(sources), 'primary_lags': primaries,
                    'synergy_bits': r['synergy'], 'synergy_is_group_quantity': True,
                    'joint_information_bits': r['joint_information'], 'redundancy_bits': r['redundancy'],
                    'joint_calibration': joint['calibration'], 'synergy_calibration': synergy['calibration'],
                    'joint_adjusted_p_value': correction['hypotheses'][joint_key]['adjusted_p_value'],
                    'synergy_adjusted_p_value': correction['hypotheses'][synergy_key]['adjusted_p_value']})
        decisions.append({'method': 'lagged_mmi_pid', 'target': target, 'sources': sources, 'joint_accepted': bool(okay),
                          'upstream_reason': r.get('reason'),
                          'upstream_status': r.get('status'), 'reason': 'complete joint predictive evidence' if okay else
                          'joint support/calibration/completeness absent; marginal evidence assessed separately'})
    occupied = {e['edge_id'] for e in graph['edges']}
    for target, record in lags.items():
        if target not in valid: continue
        selected = [v for v in record.get('self_evidence', []) if type(v.get('lag')) is int and v['lag'] > 0 and
                    at_least(v.get('validation_gain'), cfg['lag']['min_absolute_gain']) and passed(f's:{target}:{v["lag"]}', v)]
        decisions.append({'method': 'rnn_lag', 'target': target, 'accepted': bool(selected),
                          'upstream_status': record.get('status'), 'upstream_reason': record.get('reason'),
                          'reason': 'independent confirmation and multiplicity rules' if selected else 'no confirmed stable self-memory; not a claim of absence'})
        if not selected: continue
        values = sorted({v['lag'] for v in selected})
        primary = record.get('primary_self_lag')
        if primary not in values: primary = max(selected, key=lambda v: v['validation_gain'])['lag']
        edge_id = 'self_memory__' + target
        while edge_id in occupied: edge_id += '_generated'
        occupied.add(edge_id)
        accepted[(target, target)] = {'edge_id': edge_id, 'source': target, 'target': target, 'weight': primary, 'lags': values,
            'relation_type': 'self_memory', 'scale_direction': 'intra_scale', 'method': 'rnn_lag', 'status': 'accepted',
            'evidence': [{'kind': 'self_memory', 'method': 'rnn_lag', 'status': 'accepted', 'lag': v['lag'],
                 'calibration': v['calibration'], 'validation_gain': v['validation_gain'],
                 'adjusted_p_value': correction['hypotheses'][f's:{target}:{v["lag"]}']['adjusted_p_value']} for v in selected]}
    final_nodes = []
    for iid, node in original_nodes.items():
        if iid in valid:
            copied = deepcopy(node); copied.update(node_id=iid, indicator_id=iid,
                analysis_transformations=deepcopy(data.get('transformations', {}).get(iid, {})))
            final_nodes.append(copied)
    for edge in accepted.values():
        groups = [e for e in edge['evidence'] if e['kind'] == 'pid_joint']
        if len(groups) == 1:
            edge.update(joint_group_id=groups[0]['joint_group_id'], joint_sources=groups[0]['joint_sources'])
    final = serializable({'schema_version': 'causal-discovery/1.0', 'source_graph': data.get('source_graph', 'in_memory_graph'),
        'weight_semantics': 'primary_lag_in_simulation_steps', 'evidence_scope': 'observational directed predictive dependence and joint information, not structural causal truth',
        'nodes': final_nodes, 'edges': list(accepted.values()), 'run_ids': graph.get('run_ids', []),
        'source_graph_sha256': data.get('source_sha256'), 'multiplicity': {'method': cfg['decision']['correction'], 'valid_tests': correction['tested_count']}})
    validate_final_graph(final)
    removed = deepcopy(data.get('invalid_nodes', {}))
    for iid in set(original_nodes) - valid:
        removed.setdefault(iid, {'reason': 'not admitted by M1; no additional explanation supplied by caller'})
    candidate_decisions = [{'edge_id': e['edge_id'], 'source': e['source'], 'target': e['target'],
        'status': 'accepted' if (e['source'], e['target']) in accepted else 'removed_invalid_node' if
                  e['source'] not in valid or e['target'] not in valid else 'not_accepted',
        'reason': 'retained evidence is in final edge' if (e['source'], e['target']) in accepted else
                  'invalid endpoint' if e['source'] not in valid or e['target'] not in valid else
                  'no complete calibrated evidence passed the predeclared route/lag/gain/correction rules; not absence'} for e in graph['edges']]
    audit = serializable({'removed_nodes': removed, 'candidate_edge_decisions': candidate_decisions,
        'removed_incident_edges': [deepcopy(e) for e in graph['edges'] if e['source'] not in valid or e['target'] not in valid],
        'external_parent_counts': {k: len(v) for k, v in parents.items()}, 'decisions': decisions, 'correction': correction,
        'valid_isolated_nodes': [n for n in valid if not any(e['source'] == n or e['target'] == n for e in final['edges'])],
        'higher_order_pid_evaluated': False, 'nonacceptance_is_not_absence': True})
    return {'graph': final, 'audit': audit}


def demo_payload() -> dict:
    # Artificial evidence is explicitly permitted for testing this integration-only module.
    names = ['A', 'B', 'Y', 'T', 'bad']
    graph = {'nodes': [{'node_id': n, 'indicator_id': n, 'scale': 'macro' if n in ('Y', 'bad') else 'micro',
                       'phenomenon_id': 'rule_fixture', 'name': n, 'mathematical_definition': f'recorded {n}(t)'} for n in names],
             'edges': [{'edge_id': f'e{i}', 'source': a, 'target': b, 'relation_type': 'semantic_candidate'}
                       for i, (a, b) in enumerate([('A', 'Y'), ('B', 'Y'), ('A', 'T'), ('T', 'A'), ('bad', 'T')])], 'run_ids': ['fixture']}
    calibration = {'p_value': .001, 'p_value_valid': True, 'method': 'ARTIFICIAL M5 RULE FIXTURE ONLY'}
    rejected = {'p_value': .8, 'p_value_valid': True, 'method': 'ARTIFICIAL M5 RULE FIXTURE ONLY'}
    lags = [{'target': t, 'parent_lags': ps, 'primary_lags': {p: v[0] for p, v in ps.items()},
             'parent_status': {p: 'estimated' for p in ps}, 'self_evidence': []}
            for t, ps in [('Y', {'A': [2], 'B': [3]}), ('T', {'A': [2]}), ('A', {'T': [1]})]]
    lags[1].update(primary_self_lag=1, self_evidence=[{'lag': 1, 'validation_gain': .2, 'status': 'supported', 'calibration': calibration}])
    granger = [{'source': a, 'target': b, 'primary_lag': lag, 'lags': [lag], 'prediction_gain': .4, 'status': 'supported',
                 'calibration': calibration} for a, b, lag in [('A', 'T', 2), ('T', 'A', 1)]]
    pid = {'sources': ['A', 'B'], 'target': 'Y', 'source_lags': {'A': [2], 'B': [3]}, 'primary_lags': {'A': 2, 'B': 3},
           'synergy': 1.0, 'redundancy': 0.0, 'joint_information': 1.0, 'unique': {'A': 0.0, 'B': 0.0}, 'status': 'supported',
           'tests': {k: {'gain_bits': 1.0 if k in ('joint', 'synergy') else 0.0,
                         'status': 'supported' if k in ('joint', 'synergy') else 'rejected',
                         'calibration': calibration if k in ('joint', 'synergy') else rejected}
                     for k in ('marginal_1', 'marginal_2', 'joint', 'synergy')}}
    return {'graph': graph, 'data': {'valid_nodes': names[:-1], 'invalid_nodes': {'bad': {'reason': 'synthetic invalid data rule test'}},
              'source_graph': 'M5 artificial rule fixture, not algorithm-estimated evidence'}, 'lag_results': lags,
            'granger_results': granger, 'pid_results': [pid]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true'); parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--config', type=Path)
    args = parser.parse_args(argv)
    payload = demo_payload() if args.demo else read_json(args.input) if args.input else None
    if payload is None: parser.error('Use --demo or --input')
    result = integrate_graph(**payload, config=args.config)
    output = args.output or (Path('causal_discovery/results/independent/m5_demo_final.json') if args.demo else None)
    emit(result['graph'], output)
    if output:
        save_json(output.with_suffix('.audit.json'), result['audit']); print(str(output))


if __name__ == '__main__': main()
