"""M1: explicit observation-unit adaptation of executable_graph.json or arrays."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

from ._common import align_runs, as_matrix, emit, make_windows, read_json, serializable, settings, sha256


def align_arrays(x: Any, y: Any, steps: Any = None, min_samples: int = 3) -> dict:
    """Check and jointly align two time × feature arrays; no imputation."""
    x, y = as_matrix(x), as_matrix(y)
    axis = np.arange(len(x)) if steps is None else np.asarray(steps)
    if len(x) != len(y) or len(axis) != len(x):
        raise ValueError('x, y and steps must have equal lengths')
    frame = pd.DataFrame({'step': axis})
    if not is_numeric_dtype(frame.step) or not np.isfinite(axis).all() or not (axis == np.floor(axis)).all() or frame.step.duplicated().any():
        raise ValueError('Time indices must be unique finite integers')
    if np.isinf(x).any() or np.isinf(y).any():
        raise ValueError('Infinite values are invalid')
    order = np.argsort(axis); x, y, axis = x[order], y[order], axis[order].astype(int)
    finite = np.isfinite(x).all(axis=1) & np.isfinite(y).all(axis=1)
    x, y, axis = x[finite], y[finite], axis[finite]
    reasons = []
    if len(x) < min_samples: reasons.append('insufficient finite aligned observations')
    if len(x) and (np.any(np.ptp(x, axis=0) <= 1e-12) or np.any(np.ptp(y, axis=0) <= 1e-12)):
        reasons.append('constant feature is not a dynamic series')
    stride = int(np.gcd.reduce(np.diff(axis))) if len(axis) > 1 else None
    return serializable({'status': 'valid' if not reasons else 'invalid', 'x': x, 'y': y, 'steps': axis,
                         'report': {'finite_rows': len(x), 'excluded_missing_rows': int((~finite).sum()),
                                    'step_size': stride, 'gaps_present': bool(len(axis) > 1 and np.any(np.diff(axis) != stride)),
                                    'reasons': reasons, 'transformation': 'joint finite-row selection; no filling or resampling'}})


def _entity(value: Any) -> str:
    if isinstance(value, str):
        try: value = json.loads(value)
        except ValueError: return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _adapt_frame(frame: pd.DataFrame, options: dict) -> tuple[pd.DataFrame, dict]:
    if frame.empty or not {'step', 'feature', 'value'} <= set(frame):
        raise ValueError('Missing or empty step/feature/value observations')
    if not is_numeric_dtype(frame.value) or np.isinf(frame.value.astype(float)).any():
        raise ValueError('Values must be numeric and cannot contain infinity')
    if not is_numeric_dtype(frame.step) or frame.step.isna().any() or not np.isfinite(frame.step).all() or not (frame.step == np.floor(frame.step)).all():
        raise ValueError('step must contain finite integers')
    frame = frame.copy(); frame['step'] = frame.step.astype(np.int64)
    available = sorted(frame.feature.unique().tolist())
    if any(not isinstance(f, str) for f in available):
        raise ValueError('Feature identifiers must be strings')
    requested = options.get('features', [options['feature']] if 'feature' in options else None)
    if requested is None:
        if len(available) != 1:
            raise ValueError('Multiple features require an explicit feature/features selection')
        requested = available
    if not isinstance(requested, list) or not requested or len(requested) != len(set(requested)) or not set(requested) <= set(available):
        raise ValueError('Invalid explicit feature selection')
    frame = frame[frame.feature.isin(requested)]
    entities = 'entity_id' in frame
    keys = ['step', 'feature'] + (['entity_id'] if entities else [])
    if frame.duplicated(keys).any():
        raise ValueError('Duplicate observation coordinate')
    transform = {'features': requested, 'input_entity_level': entities, 'aggregation': None,
                 'formula': 'V_f(t) = recorded value of explicitly selected feature f at step t'}
    if entities:
        if frame.entity_id.isna().any(): raise ValueError('Missing entity identifier')
        frame['entity_id'] = frame.entity_id.map(_entity)
        mode = options.get('entity_mode')
        if mode == 'aggregate':
            aggregation = options.get('aggregation')
            if aggregation not in ('mean', 'median', 'sum'):
                raise ValueError('Explicit entity aggregation must be mean, median or sum')
            grouped = frame.groupby(['step', 'feature'], sort=True)['value']
            missing = options.get('aggregation_missing', 'propagate')
            if missing not in ('propagate', 'observed'):
                raise ValueError('aggregation_missing must be propagate or observed')
            values = grouped.agg(lambda a: np.nan if missing == 'propagate' and a.isna().any() else getattr(a, aggregation)())
            matrix = values.unstack('feature').reindex(columns=requested)
            transform.update(aggregation=aggregation, analysis_unit='run_step', entity_mode=mode,
                             formula=f'V_f(t) = {aggregation}_{{e in recorded E_t}} v_ef(t); missing={missing}',
                             contributing_entity_counts=frame.groupby('step').entity_id.nunique().to_dict())
        elif mode == 'select':
            if 'entity_id' not in options: raise ValueError('Explicit entity_id is required')
            entity = _entity(options['entity_id'])
            selected = frame[frame.entity_id == entity]
            if selected.empty: raise ValueError('Selected entity absent from this run')
            matrix = selected.pivot(index='step', columns='feature', values='value').reindex(columns=requested)
            transform.update(analysis_unit='selected_entity_step', entity_mode=mode, entity_id=entity,
                             formula=f'V_f(t) = v_ef(t) for explicitly fixed entity e={entity}')
        elif mode == 'features':
            selected = [_entity(e) for e in options.get('entity_ids', [])]
            if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(frame.entity_id):
                raise ValueError('Explicit existing entity_ids required for vector mapping')
            columns = pd.MultiIndex.from_product([requested, selected])
            matrix = frame[frame.entity_id.isin(selected)].pivot(index='step', columns=['feature', 'entity_id'], values='value').reindex(columns=columns)
            matrix.columns = [f'{f}@{e}' for f, e in matrix.columns]
            transform.update(analysis_unit='explicit_entity_vector_at_one_step', entity_mode=mode, entity_ids=selected,
                             formula='V(t) = ordered vector (v_ef(t)) for explicitly selected (feature, entity) pairs; one row per step')
        else:
            raise ValueError('Entity observations require explicit entity_mode=select/aggregate/features; no automatic mean')
    else:
        matrix = frame.pivot(index='step', columns='feature', values='value').reindex(columns=requested)
        transform['analysis_unit'] = 'run_step'
    return matrix.sort_index().astype(float), transform


def adapt_graph(graph: str | Path | Mapping, config: Mapping | str | Path | None = None, *, base_dir: str | Path | None = None) -> dict:
    """Read actual Parquet or explicit demo arrays; reject invalid nodes, never replicate macro rows."""
    cfg = settings(config); data_cfg = cfg['data']
    path = Path(graph).resolve() if isinstance(graph, (str, Path)) else None
    source = read_json(path) if path else deepcopy(dict(graph))
    base = Path(base_dir).resolve() if base_dir else path.parent if path else Path.cwd()
    nodes, edges = source.get('nodes', []), source.get('edges', [])
    ids = [n.get('node_id', n.get('indicator_id')) for n in nodes]
    if len(ids) != len(set(ids)) or any(not isinstance(i, str) or not i for i in ids):
        raise ValueError('Unique nonempty node IDs required')
    edge_ids = [e.get('edge_id') for e in edges]
    if len(edge_ids) != len(set(edge_ids)) or any(not isinstance(e, str) for e in edge_ids):
        raise ValueError('Unique candidate edge IDs required')
    if any(e.get('source') not in ids or e.get('target') not in ids for e in edges):
        raise ValueError('Candidate edge references an absent node')
    runs = source.get('run_ids', [])
    if not runs or len(set(runs)) != len(runs): raise ValueError('Unique run_ids are required')
    valid, invalid, series, transforms, reports = [], {}, {}, {}, {}
    for node, iid in zip(nodes, ids):
        node_runs, node_transforms, node_report = {}, {}, {'runs': {}, 'source_files': {}}
        try:
            options = data_cfg['node_overrides'].get(iid, {})
            total = 0
            for rid in runs:
                if 'demo_series' in source:
                    item = source['demo_series'][iid][rid]
                    values = as_matrix(item.get('values', item) if isinstance(item, dict) else item)
                    axis = item.get('steps', list(range(len(values)))) if isinstance(item, dict) else list(range(len(values)))
                    features = item.get('features', [f'value_{i}' for i in range(values.shape[1])]) if isinstance(item, dict) else ['value']
                    if len(features) != values.shape[1]: raise ValueError('Demo feature count differs from values')
                    frame = pd.DataFrame({'step': np.repeat(axis, len(features)), 'feature': np.tile(features, len(values)),
                                          'value': values.ravel()})
                else:
                    execution = node.get('execution', {}).get(rid)
                    if not execution or execution.get('status') != 'success': raise ValueError(f'{rid}: source execution not successful')
                    file = Path(execution['series_file'])
                    if not file.is_absolute():
                        candidates = [directory / file for directory in (base, *base.parents)]
                        file = next((p for p in candidates if p.is_file()), base / file)
                    if execution.get('series_sha256') and sha256(file) != execution['series_sha256']:
                        raise ValueError(f'{rid}: series SHA-256 differs from the execution record')
                    frame = pd.read_parquet(file)
                    if not {'run_id', 'indicator_id'} <= set(frame): raise ValueError('Missing run/indicator identifiers')
                    frame = frame[(frame.run_id == rid) & (frame.indicator_id == iid)]
                    node_report['source_files'][rid] = {'path': str(file.resolve()), 'sha256': sha256(file), 'raw_rows': len(frame)}
                matrix, transformation = _adapt_frame(frame, options)
                finite_rows = np.isfinite(matrix.to_numpy()).all(axis=1)
                missing = float(1 - finite_rows.mean()) if len(matrix) else 1.0
                constants = [name for name in matrix if matrix[name].dropna().empty or np.ptp(matrix[name].dropna()) <= data_cfg['constant_tolerance']]
                node_report['runs'][rid] = {'rows': len(matrix), 'finite_rows': int(finite_rows.sum()), 'missing_fraction': missing,
                                          'constant_features': constants, 'features': list(matrix.columns),
                                          'transformation': transformation}
                if constants:
                    raise ValueError(f'{rid}: constant/run-level scalar broadcast or all-missing features: {constants}')
                if missing > data_cfg['max_missing_fraction']:
                    raise ValueError(f'{rid}: missing fraction {missing:.3f} exceeds configured limit')
                if int(finite_rows.sum()) < data_cfg['min_samples_per_run']:
                    raise ValueError(f'{rid}: insufficient finite samples per run')
                steps = matrix.index.to_numpy()
                stride = int(np.gcd.reduce(np.diff(steps))) if len(steps) > 1 else 0
                if stride <= 0: raise ValueError('Nonpositive time cadence')
                node_report['runs'][rid].update(step_size=stride, gap_count=int(np.count_nonzero(np.diff(steps) != stride)))
                total += int(finite_rows.sum())
                node_runs[rid] = serializable({'steps': steps, 'values': matrix.to_numpy(), 'features': list(matrix.columns), 'step_size': stride})
                node_transforms[rid] = transformation
            if len({r['step_size'] for r in node_runs.values()}) != 1:
                raise ValueError('Different sampling intervals between random-seed runs')
            if total < data_cfg['min_total_observations']:
                raise ValueError(f'insufficient dynamic observations: {total} < {data_cfg["min_total_observations"]}')
            arrays, _ = align_runs({r: item['values'] for r, item in node_runs.items()},
                                   steps={r: item['steps'] for r, item in node_runs.items()})
            windows = make_windows(arrays, cfg)
            node_report['analysis_eligibility'] = windows['split_report']
            insufficient = {role: len(group['y']) for role, group in windows['groups'].items()
                            if len(group['y']) < cfg['split']['min_windows'][role]}
            if insufficient:
                raise ValueError(f'insufficient within-run windows for separate analysis partitions: {insufficient}')
            valid.append(iid); series[iid] = node_runs; transforms[iid] = node_transforms
        except (ValueError, KeyError, TypeError, OSError) as exc:
            invalid[iid] = {'reason': f'{type(exc).__name__}: {exc}', 'report': node_report}
        reports[iid] = node_report
    kept = [deepcopy(e) for e in edges if e['source'] in valid and e['target'] in valid and e['source'] != e['target']]
    return serializable({'module': 'M1', 'valid_nodes': valid, 'valid_edges': kept, 'series': series,
                         'data_origin': 'explicit_demo_arrays' if 'demo_series' in source else 'actual_parquet',
                         'transformations': transforms, 'invalid_nodes': invalid, 'data_report': reports,
                         'run_ids': runs, 'source_graph': str(path) if path else 'in_memory_graph',
                         'source_sha256': sha256(path) if path else None, 'config': cfg['data']})


def align_target(data: Mapping, target: str, parents: list[str]) -> dict:
    """One row per common simulation step; never copy a target across subject records."""
    ids = [target, *parents]; out = {'y': {}, 'parents': {p: {} for p in parents}, 'steps': {}, 'alignment': {}}
    for rid in data['run_ids']:
        arrays = {}
        for iid in ids:
            item = data['series'][iid][rid]
            arrays[iid] = pd.DataFrame(item['values'], index=item['steps'])
        common = sorted(set.intersection(*(set(a.index) for a in arrays.values())))
        if not common: raise ValueError(f'{rid}: no common actual step')
        out['y'][rid] = arrays[target].loc[common].to_numpy().tolist()
        out['steps'][rid] = common
        for parent in parents: out['parents'][parent][rid] = arrays[parent].loc[common].to_numpy().tolist()
        out['alignment'][rid] = {'actual_common_steps': len(common), 'row_unit': 'one vector per run and step; no entity replication'}
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true'); parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--config', type=Path)
    args = parser.parse_args(argv)
    if args.demo:
        parameters = settings(args.config)['demo']
        rng = np.random.default_rng(parameters['m1_seed']); x = rng.normal(size=parameters['m1_length'])
        result = align_arrays(x, .4 * x + rng.normal(size=len(x)), np.arange(len(x)))
    elif args.input:
        payload = read_json(args.input)
        result = adapt_graph(args.input, args.config) if 'nodes' in payload else align_arrays(payload['x'], payload['y'], payload.get('steps'), payload.get('min_samples', 3))
    else: parser.error('Use --demo or --input')
    emit(result, args.output)


if __name__ == '__main__': main()
