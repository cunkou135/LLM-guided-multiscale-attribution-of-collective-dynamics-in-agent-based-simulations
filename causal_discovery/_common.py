"""Shared I/O, explicit configuration and dependence-aware score calibration.

None of the five independent algorithms imports another m-module.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

ROLES = ('train', 'validation', 'confirmation', 'test')
TARGET = '__target__'


def serializable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [serializable(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def read_json(path: str | Path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda text: (_ for _ in ()).throw(ValueError(f'Invalid JSON number: {text}')))


def save_json(path: str | Path, result: Any) -> None:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serializable(result), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def seed_for(config: dict, label: str) -> int:
    """Deterministic substreams from the configured seed, independent of Python hash salt."""
    return int.from_bytes(hashlib.sha256(f'{config["random_seed"]}:{label}'.encode()).digest()[:4], 'little')


def settings(config: Mapping | str | Path | None = None) -> dict:
    base = yaml.safe_load(Path(__file__).with_name('config.yaml').read_text(encoding='utf-8'))
    if config is None:
        return base
    overrides = yaml.safe_load(Path(config).read_text(encoding='utf-8')) if isinstance(config, (str, Path)) else config
    def merge(a, b, prefix=''):
        if not isinstance(b, Mapping):
            raise ValueError(f'{prefix}: expected a configuration mapping')
        if a:
            unknown = set(b) - set(a)
            if unknown:
                raise ValueError(f'{prefix}: unknown configuration keys {sorted(unknown)}')
        result = deepcopy(a)
        for key, value in b.items():
            result[key] = merge(a[key], value, prefix + key + '.') if key in a and isinstance(a[key], dict) else deepcopy(value)
        return result
    cfg = merge(base, overrides)
    fractions = cfg['split']['fractions']
    if len(fractions) != 4 or any(v <= 0 for v in fractions) or not np.isclose(sum(fractions), 1):
        raise ValueError('Four positive train/validation/confirmation/test fractions must sum to one')
    if any(type(cfg['rnn'][key]) is not int or cfg['rnn'][key] < 1 for key in ('max_lag', 'epochs', 'hidden_size', 'batch_size')):
        raise ValueError('Positive integer RNN dimensions/budgets required')
    if not 0 < cfg['calibration']['alpha'] < 1 or not 0 < cfg['decision']['alpha'] < 1:
        raise ValueError('alpha must be within (0,1)')
    if cfg['calibration']['bootstrap_repeats'] < 99 or cfg['calibration']['block_length'] < 1:
        raise ValueError('Calibration requires at least 99 resamples and positive block length')
    return cfg


def as_matrix(values: Any) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim == 1:
        array = array[:, None]
    if array.ndim != 2 or array.shape[1] < 1:
        raise ValueError('Expected time × feature numeric array')
    return array


def align_runs(y: Any, parents: Mapping[str, Any] | None = None, steps: Any = None) -> tuple[list[dict], dict]:
    """Arrays or run-keyed arrays, aligned without constructing cross-run rows."""
    parents = parents or {}
    if TARGET in parents: raise ValueError('Reserved internal target label')
    targets = y if isinstance(y, Mapping) else {'run_0': y}
    series, dimensions = [], {}
    for rid, target in targets.items():
        target = as_matrix(target)
        axis = steps.get(rid) if isinstance(steps, Mapping) else steps
        axis = np.arange(len(target)) if axis is None else np.asarray(axis)
        if axis.ndim != 1 or len(axis) != len(target) or not np.issubdtype(axis.dtype, np.number):
            raise ValueError('steps must be one numeric coordinate per observation')
        if not np.isfinite(axis).all() or not (axis == np.floor(axis)).all() or len(set(axis)) != len(axis):
            raise ValueError('steps must be finite unique integers')
        order = np.argsort(axis); axis = axis[order].astype(np.int64)
        arrays = {TARGET: target[order]}
        for name, source in parents.items():
            value = source.get(rid) if isinstance(source, Mapping) else source
            if value is None:
                raise ValueError(f'{name}: missing run {rid}')
            value = as_matrix(value)
            if len(value) != len(target):
                raise ValueError(f'{name}: length differs from target; align time coordinates first')
            arrays[name] = value[order]
        for name, value in arrays.items():
            if np.isinf(value).any():
                raise ValueError(f'{name}: infinite observations')
            if name in dimensions and dimensions[name] != value.shape[1]:
                raise ValueError('Feature dimensions differ between runs')
            dimensions[name] = value.shape[1]
        series.append({'run_id': str(rid), 'steps': axis, 'arrays': arrays})
    return series, dimensions


def make_windows(runs: list[dict], cfg: dict) -> dict:
    """Split runs first, or purge chronological partitions; windows stay wholly inside one role/run."""
    lag = cfg['rnn']['max_lag']
    strides = [int(np.gcd.reduce(np.diff(r['steps']))) for r in runs if len(r['steps']) > 1]
    if not strides or len(set(strides)) != 1 or strides[0] <= 0:
        raise ValueError('Runs require one common positive sampling interval')
    dt = strides[0]
    order = list(runs[0]['arrays'])
    slices, offset = {}, 0
    for name in order:
        width = runs[0]['arrays'][name].shape[1]
        slices[name] = [offset, offset + width]; offset += width
    roles = cfg['split']['run_roles']
    run_names = [r['run_id'] for r in runs]
    if roles:
        if set(roles) != set(run_names) or any(v not in ROLES for v in roles.values()):
            raise ValueError('Explicit run_roles must assign each run once to a known partition')
        assigned = dict(roles); mode = 'independent_runs'
    elif len(runs) >= 4:
        rng = np.random.default_rng(cfg['random_seed'])
        indices = rng.permutation(len(runs)).tolist()
        counts = np.ones(4, dtype=int)
        for _ in range(len(runs) - 4):
            desired = np.array(cfg['split']['fractions']) * len(runs) - counts
            counts[int(np.argmax(desired))] += 1
        assigned = {}; start = 0
        for role, count in zip(ROLES, counts):
            for index in indices[start:start + count]: assigned[run_names[index]] = role
            start += count
        mode = 'independent_runs'
    else:
        assigned = {}; mode = 'purged_chronological_within_runs'
    groups = {role: {'x': [], 'y': [], 'run_ids': [], 'steps': []} for role in ROLES}
    for run in runs:
        axis = run['steps']; values = np.concatenate([run['arrays'][name] for name in order], axis=1)
        if assigned:
            bounds = [(assigned[run['run_id']], 0, len(axis))]
        else:
            cuts = np.r_[0, np.cumsum(cfg['split']['fractions']) * len(axis)].astype(int)
            cuts[-1] = len(axis)
            bounds = [(role, int(cuts[i]), int(cuts[i + 1])) for i, role in enumerate(ROLES)]
        for role, begin, end in bounds:
            for t in range(begin + lag, end):
                if not np.all(np.diff(axis[t - lag:t + 1]) == dt):
                    continue
                history, target = values[t - lag:t], run['arrays'][TARGET][t]
                if not np.isfinite(history).all() or not np.isfinite(target).all():
                    continue
                group = groups[role]
                group['x'].append(history); group['y'].append(target)
                group['run_ids'].append(run['run_id']); group['steps'].append(int(axis[t]))
    for role, group in groups.items():
        group['x'] = np.asarray(group['x'], dtype=np.float64).reshape(-1, lag, offset)
        group['y'] = np.asarray(group['y'], dtype=np.float64).reshape(-1, runs[0]['arrays'][TARGET].shape[1])
    return {'groups': groups, 'slices': slices, 'step_size': dt, 'max_lag': lag,
            'split_report': {'mode': mode, 'run_roles': assigned, 'windows': {r: len(g['y']) for r, g in groups.items()},
                             'no_window_crosses_run_or_partition': True,
                             'limitations': [] if assigned else ['Temporal splits are not independent new random seeds; weak stationarity/mixing are assumptions.']}}


def calibrate_gain(differences: Mapping[str, Any], config: dict | None = None, seed: int | None = None) -> dict:
    """One-sided centered moving-block bootstrap of a fixed held-out score difference.

    Null: expected predictive score gain <= 0. This is an approximate loss/log-score
    test, not an exact conditional-independence or structural-causality p-value.
    """
    cfg = settings(config); c = cfg['calibration']
    arrays = [np.asarray(v, dtype=float).ravel() for v in differences.values()]
    arrays = [v for v in arrays if len(v)]
    assumptions = ['held-out predictions fixed before evaluation', 'weakly stationary, weakly dependent score differences within runs',
                   'independent random-seed runs when more than one run is resampled']
    result = {'method': 'centered_moving_block_bootstrap', 'null': 'expected heldout predictive score gain <= 0',
              'p_value': None, 'p_value_valid': False, 'assumptions': assumptions,
              'p_value_scope': 'approximate predictive-score test, not structural or exact conditional independence',
              'repeats': c['bootstrap_repeats'], 'block_length': c['block_length'], 'run_count': len(arrays)}
    if not arrays or any(len(v) < max(16, 2 * c['block_length']) or not np.isfinite(v).all() for v in arrays):
        return {**result, 'reason': 'insufficient finite held-out observations for block calibration'}
    observed = float(np.mean([v.mean() for v in arrays]))
    result['gain'] = observed
    if not c['assume_weak_stationarity']:
        return {**result, 'reason': 'stationarity/mixing assumptions not declared'}
    shifts = []
    for values in arrays:
        sd = float(values.std())
        shift = float(np.ptp([a.mean() for a in np.array_split(values, 4)]) / max(sd, 1e-12))
        shifts.append(shift)
    result['block_mean_shift_sd'] = shifts
    if max(shifts) > c['max_block_mean_shift_sd']:
        return {**result, 'reason': 'score stationarity diagnostic failed; no calibrated p-value claimed'}
    rng = np.random.default_rng(cfg['random_seed'] if seed is None else seed)
    bootstrap = []
    for _ in range(c['bootstrap_repeats']):
        selected = rng.integers(len(arrays), size=len(arrays)) if len(arrays) > 1 else [0]
        means = []
        for index in selected:
            values = arrays[index]; block = c['block_length']
            starts = rng.integers(0, len(values) - block + 1, size=int(np.ceil(len(values) / block)))
            sample = np.concatenate([values[s:s + block] for s in starts])[:len(values)]
            means.append(float(sample.mean()))
        bootstrap.append(float(np.mean(means)))
    null = np.asarray(bootstrap) - observed
    p = float((1 + np.count_nonzero(null >= observed)) / (len(null) + 1))
    lower, upper = np.quantile(bootstrap, [c['alpha'] / 2, 1 - c['alpha'] / 2])
    return {**result, 'p_value': p, 'p_value_valid': True, 'confidence_interval': [float(lower), float(upper)],
            'finite_samples': int(sum(map(len, arrays))), 'seed': cfg['random_seed'] if seed is None else seed}


def emit(result: dict, output: str | Path | None) -> dict:
    result = serializable(result)
    if output:
        save_json(output, result)
    else:
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return result
