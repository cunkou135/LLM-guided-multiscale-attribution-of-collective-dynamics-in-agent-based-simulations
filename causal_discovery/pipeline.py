"""M1→M2→(single-parent M3 / paired multi-parent M4)→M5; no LLM calls."""
import argparse
import hashlib
from copy import deepcopy
from itertools import combinations
from pathlib import Path
import platform
import sys
import time

import numpy as np

from ._common import read_json, save_json, serializable, settings, sha256
from .m1_data import adapt_graph, align_target
from .m2_lag_rnn import estimate_lags
from .m3_granger import test_granger
from .m4_pid import lagged_mmi_pid
from .m5_graph import integrate_graph, validate_final_graph


def pid_pair_plan(parents: list[str], maximum: int) -> dict:
    """Fixed lexical pairs, with all unassessed pairs explicitly listed."""
    if type(maximum) is not int or maximum < 1: raise ValueError('max_pairs must be positive')
    pairs = list(combinations(sorted(set(parents)), 2))
    return {'pair_strategy': 'lexicographic predeclared first max_pairs, no data-dependent search',
            'evaluated_pairs': [list(p) for p in pairs[:maximum]], 'omitted_pairs': [list(p) for p in pairs[maximum:]],
            'higher_order_synergy_evaluated': False}


def make_demo_graph(config: dict | None = None) -> dict:
    """Seeded observations only. Generating lag truth is not passed to any estimator."""
    cfg = settings(config); d = cfg['demo']; names = ['X', 'A', 'B', 'Y', 'Z', 'W', 'bad']
    scales = dict(zip(names, ['micro', 'micro', 'meso', 'macro', 'macro', 'meso', 'macro']))
    runs = [f'seed_{d["pipeline_seed"] + i}' for i in range(d['pipeline_runs'])]
    series = {name: {} for name in names}
    for i, run in enumerate(runs):
        rng = np.random.default_rng(d['pipeline_seed'] + i)
        n = d['pipeline_length'] + 200
        x = rng.normal(size=n); a = rng.integers(0, 2, n); b = rng.integers(0, 2, n)
        y, z = np.zeros(n), np.zeros(n)
        for t in range(4, n):
            y[t] = .5 * y[t - 1] + 1.8 * np.sin(x[t - 2]) + .2 * rng.normal()
            z[t] = a[t - 2] ^ b[t - 3]
        values = dict(zip(names, [x, a, b, y, z, rng.normal(size=n), np.ones(n)]))
        for name, value in values.items():
            series[name][run] = {'steps': list(range(d['pipeline_length'])), 'values': value[200:].tolist(), 'features': ['value']}
    edges = [('X', 'Y'), ('Y', 'X'), ('A', 'Z'), ('B', 'Z'), ('bad', 'Y')]
    return {'schema_version': '2.0', 'evidence_status': 'synthetic_demo_candidates', 'run_ids': runs,
        'nodes': [{'node_id': name, 'indicator_id': name, 'name': f'Synthetic recorded {name}', 'scale': scales[name],
                   'phenomenon_id': 'demo', 'mathematical_definition': f'V_{name}(t) is the recorded scalar observation at step t',
                   'units': 'synthetic units'} for name in names],
        'edges': [{'edge_id': f'demo_{a}_{b}', 'source': a, 'target': b, 'relation_type': 'semantic_candidate',
                   'scale_direction': 'intra_scale' if scales[a] == scales[b] else 'bottom_up' if
                       ['micro', 'meso', 'macro'].index(scales[a]) < ['micro', 'meso', 'macro'].index(scales[b]) else 'top_down',
                   'semantic_rationale': 'Predeclared synthetic candidate, not an accepted relation'} for a, b in edges],
        'demo_series': series, 'synthetic': True,
        'generator': {'seed': d['pipeline_seed'], 'runs': d['pipeline_runs'], 'samples_per_run': d['pipeline_length'],
                      'purpose': 'nonlinear directional, joint, self-memory, independent and invalid-data controls; no generating lags passed as estimator parameters'}}


def run_pipeline(input_graph: str | Path | dict, output: str | Path, config: dict | str | Path | None = None) -> dict:
    """Execute all five real modules and save exactly one formal graph plus an audit directory."""
    cfg = settings(config); output = Path(output).resolve()
    source = Path(input_graph).resolve() if isinstance(input_graph, (str, Path)) else None
    if source == output: raise ValueError('Output cannot overwrite the first-part input graph')
    graph = read_json(source) if source else deepcopy(input_graph)
    before = sha256(source) if source else None
    audit = output.parent / (output.stem + '_audit'); audit.mkdir(parents=True, exist_ok=True)
    save_json(audit / 'parameters.json', cfg)
    started = time.monotonic()
    data = adapt_graph(source or graph, cfg)
    save_json(audit / 'm1_data.json', data)
    parents = {iid: sorted({e['source'] for e in data['valid_edges'] if e['target'] == iid and e['source'] != iid}) for iid in data['valid_nodes']}
    lag_results, granger_results, pid_results, routes = [], [], [], []
    for target in data['valid_nodes']:
        ps = parents[target]
        artifact_id = hashlib.sha256(target.encode()).hexdigest()[:16]
        try:
            aligned = align_target(data, target, ps)
            lag = estimate_lags(aligned['y'], aligned['parents'], steps=aligned['steps'], target=target,
                                config=cfg, artifact_dir=audit / 'models/m2' / artifact_id)
        except (ValueError, KeyError) as exc:
            lag = {'target': target, 'status': 'invalid_data', 'reason': str(exc), 'parent_lags': {},
                   'parent_status': {}, 'primary_lags': {}, 'self_evidence': []}
        lag_results.append(lag)
        save_json(audit / 'm2_lag_results.json', lag_results)
        route = {'target': target, 'external_parents': ps, 'external_parent_count': len(ps),
                 'method': 'm3_granger' if len(ps) == 1 else 'm4_pid' if len(ps) >= 2 else 'self_history_only'}
        routes.append(route)
        if lag['status'] == 'invalid_data':
            failure = {'target': target, 'status': 'inconclusive', 'reason': lag['reason'],
                       'tests': {}, 'upstream_lag_status': 'invalid_data'}
            if len(ps) == 1:
                granger_results.append({**failure, 'source': ps[0], 'method': 'rnn_granger'})
            elif len(ps) >= 2:
                route.update(pid_pair_plan(ps, cfg['pid']['max_pairs']))
                pid_results.extend({**failure, 'sources': pair, 'method': 'lagged_mmi_pid'} for pair in route['evaluated_pairs'])
            continue
        if len(ps) == 1:
            parent = ps[0]
            # Keep the same common observed clock used by M2. Pair-specific
            # realignment could silently change sampling intervals and lag units.
            selected = lag.get('parent_lags', {}).get(parent, []) if lag.get('parent_status', {}).get(parent) == 'estimated' else []
            record = test_granger(aligned['parents'][parent], aligned['y'], selected,
                primary_lag=lag.get('primary_lags', {}).get(parent) if selected else None,
                source=parent, target=target, steps=aligned['steps'], config=cfg, artifact_dir=audit / 'models/m3' / artifact_id)
            record['upstream_lag_status'] = lag.get('parent_status', {}).get(parent, lag['status'])
            granger_results.append(record)
        elif len(ps) >= 2:
            route.update(pid_pair_plan(ps, cfg['pid']['max_pairs']))
            for a, b in route['evaluated_pairs']:
                # Select sources from M2's common alignment, not a finer pair grid.
                selected = {s: lag.get('parent_lags', {}).get(s, []) if lag.get('parent_status', {}).get(s) == 'estimated' else [] for s in (a, b)}
                record = lagged_mmi_pid(aligned['parents'][a], aligned['parents'][b], aligned['y'], selected,
                    sources=(a, b), target=target, primary_lags=lag.get('primary_lags', {}), steps=aligned['steps'], config=cfg)
                pid_results.append(record)
        save_json(audit / 'm3_granger_results.json', granger_results)
        save_json(audit / 'm4_pid_results.json', pid_results)
    for name, values in [('m2_lag_results.json', lag_results), ('m3_granger_results.json', granger_results), ('m4_pid_results.json', pid_results)]:
        save_json(audit / name, values)
    save_json(audit / 'routing.json', routes)
    integrated = integrate_graph(graph, data, lag_results, granger_results, pid_results, cfg)
    save_json(audit / 'm5_decision_report.json', integrated['audit'])
    for report in data['data_report'].values():
        for file in report['source_files'].values():
            if sha256(file['path']) != file['sha256']: raise ValueError('Input observations changed during analysis')
    if source and sha256(source) != before: raise ValueError('Input graph changed during analysis')
    final = integrated['graph']
    final['provenance'] = {'input_graph_sha256': before, 'data_origin': data['data_origin'],
                           'observation_contract_sha256': sha256(Path(__file__).resolve().parents[1] / 'observation_contract.py'),
                           'algorithm_config_sha256': sha256(audit / 'parameters.json'), 'llm_calls': 0,
                           'audit_directory': str(audit), 'source_modules_sha256': {p.name: sha256(p) for p in Path(__file__).parent.glob('*.py')}}
    validate_final_graph(final)
    save_json(output, final)
    report = {'status': 'completed' if data['valid_nodes'] else 'no_analyzable_nodes', 'output': str(output), 'audit_directory': str(audit),
              'reason': 'empty_input_graph' if not graph['nodes'] else 'all_nodes_failed_data_admission' if not data['valid_nodes'] else None,
              'input_nodes': len(graph['nodes']), 'valid_nodes': len(final['nodes']), 'removed_nodes': len(data['invalid_nodes']),
              'accepted_edges': len(final['edges']), 'granger_tests': len(granger_results), 'pid_pairs': len(pid_results),
              'elapsed_seconds': time.monotonic() - started, 'python': sys.version, 'platform': platform.platform(),
              'input_graph_unchanged': True, 'new_llm_calls': 0, 'data_origin': data['data_origin']}
    save_json(audit / 'pipeline_report.json', report)
    return serializable({'graph': final, 'report': report})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--demo', action='store_true'); mode.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--config', type=Path)
    args = parser.parse_args(argv)
    output = args.output or (Path('causal_discovery/results/demo/demo_final_causal_graph.json') if args.demo else
                            Path('causal_discovery/results') / args.input.parent.name / 'final_causal_graph.json')
    if args.demo:
        source = output.parent / 'demo_input_graph.json'; save_json(source, make_demo_graph(settings(args.config)))
    else: source = args.input
    result = run_pipeline(source, output, args.config)
    print(__import__('json').dumps(result['report'], ensure_ascii=False))


if __name__ == '__main__': main()
