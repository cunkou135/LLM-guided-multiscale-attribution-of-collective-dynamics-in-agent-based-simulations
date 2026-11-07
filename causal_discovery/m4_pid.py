"""M4: empirical conditional MMI-PID and held-out histogram predictive evidence."""
import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ._common import TARGET, align_runs, calibrate_gain, emit, make_windows, read_json, seed_for, serializable, settings


def _matrix(values: Any) -> np.ndarray:
    array = np.asarray(values, dtype=object)
    if array.ndim == 1: array = array[:, None]
    if array.ndim != 2: raise ValueError('Expected time × state dimensions')
    if any(v is None or isinstance(v, (float, np.floating)) and not np.isfinite(v) for v in array.ravel()):
        raise ValueError('Missing or infinite states are not imputed')
    return array


class Encoder:
    """Training-only alphabets/quantile cuts; no test-driven bin selection."""
    def __init__(self, train: np.ndarray, mode: bool | str, bins: int, maximum: int):
        self.columns = []
        for column in train.T:
            unique = list(dict.fromkeys(column.tolist()))
            numeric = all(isinstance(v, (int, float, np.number, bool)) for v in unique)
            categorical = mode is True or mode == 'auto' and (not numeric or len(unique) <= maximum and all(float(v).is_integer() for v in unique))
            if categorical:
                classes = sorted(unique, key=lambda v: (str(type(v)), str(v)))
                self.columns.append({'mode': 'categorical', 'classes': classes, 'states': len(classes)})
            else:
                values = np.asarray(column, dtype=float)
                raw = np.quantile(values, np.arange(1, bins) / bins)
                # Cutpoints at observed extremes provide no actual partition.
                cuts = sorted(set(float(c) for c in raw if values.min() < c < values.max()))
                if not cuts and len(unique) > 1:
                    cuts = [float((min(unique) + max(unique)) / 2)]
                self.columns.append({'mode': 'training_quantiles', 'cuts': cuts, 'states': len(cuts) + 1})

    def transform(self, values: np.ndarray) -> tuple[np.ndarray, int]:
        columns, unknown = [], np.zeros(len(values), dtype=bool)
        for index, card in enumerate(self.columns):
            if card['mode'] == 'categorical':
                mapping = {v: i for i, v in enumerate(card['classes'])}
                encoded = np.array([mapping.get(v, len(mapping)) for v in values[:, index]], dtype=int)
                unknown |= encoded == len(mapping)
            else:
                encoded = np.searchsorted(card['cuts'], np.asarray(values[:, index], dtype=float), side='right')
            columns.append(encoded)
        return np.column_stack(columns) if columns else np.empty((len(values), 0), dtype=int), int(unknown.sum())


def conditional_mi(z: np.ndarray, a: np.ndarray, c: np.ndarray) -> float:
    """Empirical I(Z;A|C) in bits, using the same joint empirical distribution."""
    if not len(z) or len(z) != len(a) or len(z) != len(c): raise ValueError('Aligned nonempty states required')
    zz, aa, cc = [list(map(tuple, values)) for values in (z, a, c)]
    joint = Counter(zip(zz, aa, cc)); zc = Counter(zip(zz, cc)); ac = Counter(zip(aa, cc)); count_c = Counter(cc)
    value = sum(n / len(z) * np.log2(n * count_c[cv] / (zc[(zv, cv)] * ac[(av, cv)]))
                for (zv, av, cv), n in joint.items())
    if value < -1e-10: raise ValueError('Negative empirical conditional MI beyond roundoff')
    return float(max(0, value))


def _components(i1: float, i2: float, joint: float) -> dict:
    if joint < max(i1, i2) - 1e-9: raise ValueError('Joint information violates empirical monotonicity')
    redundancy = min(i1, i2)
    return {'i1': i1, 'i2': i2, 'joint_information': joint, 'redundancy': redundancy,
            'unique': {'X1': i1 - redundancy, 'X2': i2 - redundancy}, 'synergy': max(0.0, joint - max(i1, i2)), 'units': 'bit'}


def mmi_pid(x1: Any, x2: Any, y: Any, condition: Any = None, *, discrete: bool = True, bins: int = 2,
            training: Mapping[str, Any] | None = None) -> dict:
    """Direct array decomposition; tiny exact XOR arrays are valid descriptive data, not significance tests."""
    a, b, z = map(_matrix, (x1, x2, y))
    c = _matrix(condition) if condition is not None else np.empty((len(z), 0), dtype=object)
    if not (len(a) == len(b) == len(z) == len(c)): raise ValueError('All state arrays must align')
    if not discrete and training is None: raise ValueError('Continuous decomposition requires explicit training arrays for quantile boundaries')
    fitted = training or {'x1': a, 'x2': b, 'y': z, 'condition': c}
    encoded, cards = [], {}
    for name, value in (('x1', a), ('x2', b), ('y', z), ('condition', c)):
        encoder = Encoder(_matrix(fitted[name]) if name != 'condition' or c.shape[1] else c, discrete, bins, 8)
        states, _ = encoder.transform(value); encoded.append(states); cards[name] = encoder.columns
    a, b, z, c = encoded
    result = _components(conditional_mi(z, a, c), conditional_mi(z, b, c), conditional_mi(z, np.column_stack([a, b]), c))
    return {**result, 'method': 'empirical_conditional_mmi_pid', 'status': 'decomposed', 'samples': len(z),
            'estimator': cards, 'calibration': {'p_value': None, 'p_value_valid': False,
            'reason': 'descriptive decomposition only; use lagged_mmi_pid for held-out statistical evidence'},
            'limitation': 'MMI forces the weaker unique component to zero; this does not imply no effect'}


def _log_prob(train_z, train_predictors, z, predictors, states, alpha):
    contexts = list(map(tuple, train_predictors)); outcomes = list(map(tuple, train_z))
    counts = Counter(contexts); joint = Counter(zip(contexts, outcomes))
    return np.array([np.log2((joint[(tuple(ctx), tuple(value))] + alpha) / (counts[tuple(ctx)] + alpha * states))
                     for value, ctx in zip(z, predictors)]), counts


def _group(values, group):
    labels = np.asarray(group['run_ids'])
    return {rid: np.asarray(values)[labels == rid] for rid in dict.fromkeys(group['run_ids'])}


def lagged_mmi_pid(x1: Any, x2: Any, y: Any, source_lags: Mapping[str, list[int] | int], *,
                   sources: tuple[str, str] = ('X1', 'X2'), target: str = 'Y', primary_lags: Mapping[str, int] | None = None,
                   self_lags: list[int] | None = None, steps: Any = None, config: Mapping | str | Path | None = None) -> dict:
    """Lagged two-source MMI; histogram probabilities fit train, evaluated on untouched test.

    Statistical tests concern held-out conditional log-score improvement (bits),
    calibrated by within-run moving blocks, not exact conditional-independence tests.
    Synergy support requires improvement over BOTH singleton predictors: an
    intersection-union test uses the maximum of their calibrated p-values.
    """
    cfg = settings(config); p = cfg['pid']
    result = {'sources': list(sources), 'target': target, 'method': 'lagged_mmi_pid', 'status': 'inconclusive',
              'source_lags': source_lags, 'primary_lags': primary_lags or {}, 'tests': {}, 'units': 'bit',
              'config': p, 'higher_order_synergy_evaluated': False,
              'interpretation': 'conditional predictive information; not independent structural support for member edges'}
    try:
        runs, _ = align_runs(y, {sources[0]: x1, sources[1]: x2}, steps)
        data = make_windows(runs, cfg); result['split'] = data['split_report']
        insufficient = {r: len(g['y']) for r, g in data['groups'].items() if len(g['y']) < cfg['split']['min_windows'][r]}
        if insufficient: return {**result, 'reason': 'insufficient_data', 'partition_counts': insufficient}
        memory = self_lags if self_lags is not None else [i * data['step_size'] for i in range(1, data['max_lag'] + 1)]
        if not memory: raise ValueError('Temporal PID requires explicit target history conditioning')
        chosen = {s: [source_lags[s]] if isinstance(source_lags[s], int) else list(source_lags[s]) for s in sources}
        if any(not values or len(set(values)) != len(values) for values in chosen.values()):
            raise ValueError('Each source needs nonempty unique M2 lag candidates')
        def extract(group, name, lags):
            start, end = data['slices'][name]
            pieces = []
            for lag in lags:
                if type(lag) is not int or lag <= 0 or lag % data['step_size'] or lag // data['step_size'] > data['max_lag']:
                    raise ValueError('Lag outside recorded history or sampling cadence')
                pieces.append(group['x'][:, -(lag // data['step_size']), start:end])
            return np.concatenate(pieces, axis=1)
        raw = {role: {'z': g['y'], 'a': extract(g, sources[0], chosen[sources[0]]),
                       'b': extract(g, sources[1], chosen[sources[1]]), 'c': extract(g, TARGET, memory)}
               for role, g in data['groups'].items()}
        encoders = {name: Encoder(_matrix(raw['train'][name]), p['discrete'], p['bins'], p['max_categories']) for name in ('z', 'a', 'b', 'c')}
        encoded, unseen = {}, {}
        for role, values in raw.items():
            encoded[role], unseen[role] = {}, {}
            for name, array in values.items():
                encoded[role][name], unseen[role][name] = encoders[name].transform(_matrix(array))
        result.update(source_lags=chosen, self_history_lags=memory, step_size=data['step_size'],
                      estimator={'bin_fit_partition': 'train only', 'columns': {k: v.columns for k, v in encoders.items()},
                                 'pseudocount': p['pseudocount'], 'unseen_categories': unseen})
    except (ValueError, TypeError, KeyError) as exc:
        return {**result, 'reason': f'invalid_data_or_lags: {exc}'}
    train, validation, test = (encoded[k] for k in ('train', 'validation', 'test'))
    per_run = []
    for rid, indices in _group(np.arange(len(test['z'])), data['groups']['test']).items():
        z, a, b, c = (test[key][indices] for key in ('z', 'a', 'b', 'c'))
        per_run.append([conditional_mi(z, a, c), conditional_mi(z, b, c), conditional_mi(z, np.column_stack([a, b]), c)])
    info = _components(*np.mean(per_run, axis=0))
    info['unique'] = {sources[0]: info['unique']['X1'], sources[1]: info['unique']['X2']}
    result.update(info, effective_samples=len(test['z']), run_conditioning='empirical conditional MI per run, then equal-run mean')
    target_states = int(np.prod([c['states'] for c in encoders['z'].columns]))
    possible = int(np.prod([c['states'] for encoder in encoders.values() for c in encoder.columns]))
    if possible > p['max_joint_states'] or unseen['test']['z']:
        return {**result, 'reason': 'state-space limit or unseen held-out target category; calibration not claimed', 'possible_joint_states': possible}
    if len(test['z']) < p['min_test_samples']:
        return {**result, 'reason': 'insufficient test samples'}
    def predictors(values, names): return np.concatenate([values[k] for k in names], axis=1)
    log_scores, counts = {}, {}
    combinations = {'baseline': ['c'], 'marginal_1': ['c', 'a'], 'marginal_2': ['c', 'b'], 'joint': ['c', 'a', 'b']}
    val_scores = {}
    for label, names in combinations.items():
        fit_context = predictors(train, names)
        log_scores[label], counts[label] = _log_prob(train['z'], fit_context, test['z'], predictors(test, names), target_states, p['pseudocount'])
        val_scores[label], _ = _log_prob(train['z'], fit_context, validation['z'], predictors(validation, names), target_states, p['pseudocount'])
    coverage = float(np.mean([counts['joint'][tuple(row)] >= p['min_training_cell_count'] for row in predictors(test, combinations['joint'])]))
    result['training_context_coverage'] = coverage
    if coverage < p['min_training_coverage']:
        return {**result, 'reason': 'sparse training conditional histogram; no calibrated significance claimed'}
    best_single = max(('marginal_1', 'marginal_2'), key=lambda k: np.mean([v.mean() for v in _group(val_scores[k], data['groups']['validation']).values()]))
    result['synergy_baseline_chosen_on_validation'] = best_single
    contrasts = {'marginal_1': log_scores['marginal_1'] - log_scores['baseline'],
                 'marginal_2': log_scores['marginal_2'] - log_scores['baseline'],
                 'joint': log_scores['joint'] - log_scores['baseline'],
                 'synergy_over_1': log_scores['joint'] - log_scores['marginal_1'],
                 'synergy_over_2': log_scores['joint'] - log_scores['marginal_2']}
    for i, (name, values) in enumerate(contrasts.items()):
        calibration = calibrate_gain(_group(values, data['groups']['test']), cfg, seed_for(cfg, f'pid:{target}:{sources}:{name}'))
        gain = float(np.mean([v.mean() for v in _group(values, data['groups']['test']).values()]))
        result['tests'][name] = {'gain_bits': gain, 'status': 'supported' if calibration['p_value_valid'] and
              calibration['p_value'] <= cfg['calibration']['alpha'] and gain >= p['min_information_bits'] else
              'rejected' if calibration['p_value_valid'] else 'inconclusive', 'calibration': calibration}
    comparisons = [result['tests']['synergy_over_1'], result['tests']['synergy_over_2']]
    valid = all(r['calibration']['p_value_valid'] for r in comparisons)
    p_value = max(r['calibration']['p_value'] for r in comparisons) if valid else None
    gain = min(r['gain_bits'] for r in comparisons)
    result['tests']['synergy'] = {'gain_bits': gain,
        'status': 'supported' if valid and p_value <= cfg['calibration']['alpha'] and gain >= p['min_information_bits'] else
                  'rejected' if valid else 'inconclusive',
        'calibration': {'method': 'intersection_union_of_two_block_score_tests', 'p_value': p_value, 'p_value_valid': valid,
            'null': 'joint fails to improve at least one singleton predictor',
            'component_calibrations': [r['calibration'] for r in comparisons],
            'p_value_scope': 'approximate predictive score evidence beyond BOTH singleton histograms; max of component p-values',
            'assumptions': 'Each component block calibration assumptions; no independence of the two p-values required'}}
    result['status'] = result['tests']['joint']['status']
    result['limitation'] = 'Only two-source MMI; weaker-source unique=0 is definitional, not proof of no role; no higher-order synergy claim.'
    return serializable(result)


def demo_arrays(seed=371, length=6000) -> dict:
    rng = np.random.default_rng(seed); a = rng.integers(0, 2, length); b = rng.integers(0, 2, length); y = np.zeros(length)
    y[3:] = np.bitwise_xor(a[1:-2], b[:-3])
    return {'x1': a.tolist(), 'x2': b.tolist(), 'y': y.tolist(), 'source_lags': {'X1': 2, 'X2': 3}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true'); parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--config', type=Path)
    args = parser.parse_args(argv)
    demo = settings(args.config)['demo']
    payload = demo_arrays(demo['m4_seed'], demo['m4_length']) if args.demo else read_json(args.input) if args.input else None
    if payload is None: parser.error('Use --demo or --input')
    if 'source_lags' not in payload or payload.get('static'):
        result = mmi_pid(payload['x1'], payload['x2'], payload['y'], payload.get('condition'),
                         discrete=payload.get('discrete', True), training=payload.get('training'), bins=payload.get('bins', 2))
    else:
        result = lagged_mmi_pid(payload['x1'], payload['x2'], payload['y'], payload['source_lags'],
             sources=tuple(payload.get('sources', ['X1', 'X2'])), target=payload.get('target', 'Y'),
             primary_lags=payload.get('primary_lags'),
             self_lags=payload.get('self_lags'), steps=payload.get('steps'), config=args.config or payload.get('config'))
    output = args.output or (Path('causal_discovery/results/independent/m4_demo.json') if args.demo else None)
    emit(result, output)
    if output: print(str(output))


if __name__ == '__main__': main()
