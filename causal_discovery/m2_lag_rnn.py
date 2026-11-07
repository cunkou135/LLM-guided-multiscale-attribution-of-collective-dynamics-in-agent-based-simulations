"""M2: GRU lag selection by held-out input ablation, not hidden-state weights."""
import argparse
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ._common import TARGET, calibrate_gain, emit, read_json, seed_for, serializable, settings
from ._rnn import average_run_score, by_run, fit, input_mask, losses, prepare


def estimate_lags(y: Any, parents: Mapping[str, Any] | None = None, *, steps: Any = None, target: str = 'Y',
                  config: Mapping | str | Path | None = None, artifact_dir: str | Path | None = None) -> dict:
    """Select parent/self lags on validation; confirm self memory on a separate partition.

    y can be a time series or {run_id: time×feature}; parents maps IDs to matching
    series. Reported lags are in actual simulation-step units, not sample positions.
    """
    cfg = settings(config); parents = parents or {}
    result = {'target': target, 'method': 'rnn_lag', 'parent_lags': {}, 'self_memory_lags': [],
              'primary_lags': {}, 'parent_status': {}, 'self_evidence': [], 'models': [],
              'lag_evidence': {}, 'config': cfg, 'interpretation': 'held-out predictive input-ablation sensitivity; not structural causal lag truth'}
    try:
        data = prepare(y, parents, steps, cfg)
    except (ValueError, TypeError) as exc:
        return {**result, 'status': 'invalid_data', 'reason': str(exc)}
    result.update(split=data['split_report'], step_size=data['step_size'])
    if data['inadequate']:
        return {**result, 'status': 'insufficient_data', 'reason': data['inadequate']}
    full = input_mask(data); val = data['groups']['validation']; confirm = data['groups']['confirmation']
    contributions = {name: [] for name in data['slices']}
    confirm_losses = {name: [] for name in data['slices']}
    for seed in cfg['rnn']['seeds']:
        file = Path(artifact_dir) / f'seed_{seed}.pt' if artifact_dir else None
        try:
            model, card = fit(data, full, cfg, seed, file)
        except (ValueError, RuntimeError) as exc:
            return {**result, 'status': 'training_failed', 'reason': str(exc), 'failed_seed': seed}
        result['models'].append(card)
        base = losses(model, val, full)
        confirm_base = losses(model, confirm, full)
        for name, (begin, end) in data['slices'].items():
            scores, confirmation = [], []
            for sampled in range(1, data['max_lag'] + 1):
                mask = full.copy(); mask[-sampled, begin:end] = 0
                score = losses(model, val, mask) - base
                scores.append(average_run_score(score, val))
                confirmation.append(losses(model, confirm, mask) - confirm_base)
            contributions[name].append({'scores': scores, 'baseline': average_run_score(base, val)})
            confirm_losses[name].append(confirmation)
    thresholds = cfg['lag']; dt = data['step_size']
    overall_unstable = False
    for name, per_seed in contributions.items():
        gains = np.array([v['scores'] for v in per_seed])
        bases = np.array([v['baseline'] for v in per_seed])[:, None]
        supported = (gains >= thresholds['min_absolute_gain']) & (gains >= thresholds['min_relative_gain'] * bases)
        fractions = supported.mean(axis=0)
        selected = [i + 1 for i, fraction in enumerate(fractions) if fraction >= thresholds['minimum_seed_support']]
        seed_peaks = [int(np.argmax(row)) + 1 for row in gains]
        spread = max(seed_peaks) - min(seed_peaks)
        status = 'estimated' if selected and spread <= thresholds['maximum_primary_spread'] else 'unstable' if selected else 'not_supported'
        primary = int(max(selected, key=lambda i: gains[:, i - 1].mean())) * dt if selected else None
        result['lag_evidence'][target if name == TARGET else name] = {'validation_gain_by_seed': gains.tolist(),
            'seed_support_fraction': fractions.tolist(), 'evaluated_lags': [i * dt for i in range(1, data['max_lag'] + 1)],
            'primary_sampled_lag_by_seed': seed_peaks, 'primary_spread': spread, 'status': status}
        if name == TARGET:
            result['self_memory_lags'] = [i * dt for i in selected]
            result['primary_self_lag'] = primary
            for i in selected:
                diffs = np.mean([v[i - 1] for v in confirm_losses[name]], axis=0)
                calibration = calibrate_gain(by_run(diffs, confirm), cfg, seed_for(cfg, f'self:{target}:{i}'))
                result['self_evidence'].append({'lag': i * dt, 'validation_gain': float(gains[:, i - 1].mean()),
                    'status': 'supported' if status == 'estimated' and calibration['p_value_valid'] and
                              calibration['p_value'] <= cfg['calibration']['alpha'] and calibration['gain'] >= thresholds['min_absolute_gain'] else 'inconclusive' if not calibration['p_value_valid'] or status == 'unstable' else 'rejected',
                    'calibration': calibration, 'method': 'rnn_lag_confirmation'})
        else:
            result['parent_lags'][name] = [i * dt for i in selected]
            result['primary_lags'][name] = primary
            result['parent_status'][name] = status
        overall_unstable |= status == 'unstable'
    result['status'] = 'unstable' if overall_unstable else 'estimated'
    result['test_partition_used'] = False
    return serializable(result)


def demo_arrays(seed=805, length=2400) -> dict:
    rng = np.random.default_rng(seed); x = rng.normal(size=length + 200); y = np.zeros(length + 200)
    for t in range(3, len(y)): y[t] = .55 * y[t - 2] + 1.5 * np.sin(x[t - 3]) + .15 * rng.normal()
    return {'y': y[200:].tolist(), 'parents': {'X': x[200:].tolist()}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true'); parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--config', type=Path)
    args = parser.parse_args(argv)
    demo = settings(args.config)['demo']
    payload = demo_arrays(demo['m2_seed'], demo['m2_length']) if args.demo else read_json(args.input) if args.input else None
    if payload is None: parser.error('Use --demo or --input')
    output = args.output or (Path('causal_discovery/results/independent/m2_demo.json') if args.demo else None)
    artifact = output.with_suffix('') if output else None
    result = estimate_lags(payload['y'], payload.get('parents', {}), steps=payload.get('steps'), target=payload.get('target', 'Y'),
                           config=args.config or payload.get('config'), artifact_dir=artifact)
    emit(result, output)
    if output: print(str(output))


if __name__ == '__main__': main()
