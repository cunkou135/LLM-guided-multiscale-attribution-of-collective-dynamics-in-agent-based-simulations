"""M3: one external parent, matched GRUs and held-out nonlinear predictive gain."""
import argparse
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ._common import TARGET, calibrate_gain, emit, read_json, seed_for, serializable, settings
from ._rnn import average_run_score, by_run, fit, input_mask, losses, prepare


def test_granger(x: Any, y: Any, source_lags: list[int] | None = None, *, self_lags: list[int] | None = None,
                 primary_lag: int | None = None, source: str = 'X', target: str = 'Y', steps: Any = None,
                 config: Mapping | str | Path | None = None, artifact_dir: str | Path | None = None) -> dict:
    """RNN-Granger predictive test; no PID or M2 dependency.

    Restricted/full models use identical input dimensions, hidden sizes, seeds and
    optimization budgets. Restricted external channels are structurally masked.
    Calibration tests the fixed models' expected held-out loss difference <= 0.
    """
    cfg = settings(config)
    result = {'source': source, 'target': target, 'method': 'rnn_granger', 'status': 'inconclusive',
              'lags': source_lags or [], 'primary_lag': primary_lag, 'prediction_gain': None,
              'models': [], 'config': cfg, 'loss_units': 'train-standardized mean squared error',
              'interpretation': 'directed predictive dependence conditional on target history; not structural causal effect'}
    try:
        data = prepare(y, {source: x}, steps, cfg)
        result['split'] = data['split_report']
        if data['inadequate']: return {**result, 'reason': 'insufficient_data', 'partition_counts': data['inadequate']}
        candidates = source_lags if source_lags is not None else [i * data['step_size'] for i in range(1, data['max_lag'] + 1)]
        if not candidates: return {**result, 'reason': 'no supported upstream lag candidates'}
        if len(candidates) != len(set(candidates)): raise ValueError('Duplicate lag candidates')
        memory = self_lags if self_lags is not None else [i * data['step_size'] for i in range(1, data['max_lag'] + 1)]
        if not memory: raise ValueError('Target history conditioning cannot be omitted')
        restricted = input_mask(data, {TARGET: memory})
        complete = input_mask(data, {TARGET: memory, source: candidates})
        if primary_lag is not None and primary_lag not in candidates:
            raise ValueError('Primary lag must belong to supplied lag candidates')
    except (ValueError, TypeError) as exc:
        return {**result, 'reason': f'invalid_data_or_lags: {exc}'}
    test = data['groups']['test']; val = data['groups']['validation']
    differences, seed_gains, primary_scores = [], [], []
    for seed in cfg['rnn']['seeds']:
        folder = Path(artifact_dir) / f'seed_{seed}' if artifact_dir else None
        try:
            m0, card0 = fit(data, restricted, cfg, seed, folder / 'restricted.pt' if folder else None)
            m1, card1 = fit(data, complete, cfg, seed, folder / 'full.pt' if folder else None)
        except (ValueError, RuntimeError) as exc:
            return {**result, 'reason': f'training_failed: {exc}'}
        assert card0['parameter_count'] == card1['parameter_count']
        loss0, loss1 = losses(m0, test, restricted), losses(m1, test, complete)
        difference = loss0 - loss1
        differences.append(difference); seed_gains.append(average_run_score(difference, test))
        result['models'].append({'seed': seed, 'restricted': card0, 'full': card1,
            'test_restricted_loss': average_run_score(loss0, test), 'test_full_loss': average_run_score(loss1, test)})
        baseline = losses(m1, val, complete)
        scores = []
        begin, end = data['slices'][source]
        for lag in candidates:
            mask = complete.copy(); mask[-(lag // data['step_size']), begin:end] = 0
            scores.append(average_run_score(losses(m1, val, mask) - baseline, val))
        primary_scores.append(scores)
    combined = np.mean(differences, axis=0)
    calibration = calibrate_gain(by_run(combined, test), cfg, seed_for(cfg, f'granger:{source}:{target}'))
    gain = average_run_score(combined, test)
    positive = float(np.mean(np.array(seed_gains) > 0))
    if primary_lag is None:
        primary_lag = int(candidates[int(np.argmax(np.mean(primary_scores, axis=0)))])
        primary_origin = 'validation ablation within predeclared candidate lags; test untouched'
    else: primary_origin = 'upstream M2 estimate supplied by caller'
    if not calibration['p_value_valid']:
        status = 'inconclusive'
    elif gain >= cfg['granger']['min_prediction_gain'] and calibration['p_value'] <= cfg['calibration']['alpha']:
        status = 'supported' if positive >= cfg['granger']['minimum_positive_seed_fraction'] else 'inconclusive'
    else: status = 'rejected'
    result.update(status=status, lags=candidates, primary_lag=primary_lag, primary_lag_origin=primary_origin,
        self_history_lags=memory, prediction_gain=gain, calibration=calibration, seed_gains=seed_gains,
        positive_seed_fraction=positive, validation_primary_scores=primary_scores, step_size=data['step_size'],
        test_partition_used_for_lag_selection=False,
        null_scope='expected heldout squared-loss improvement of fixed trained models; approximate time-dependent calibration')
    return serializable(result)


def demo_arrays(seed=983, length=2400, independent=False) -> dict:
    rng = np.random.default_rng(seed); x = rng.normal(size=length + 200); y = np.zeros(len(x))
    for t in range(4, len(y)):
        y[t] = .35 * y[t - 1] + (0 if independent else 1.8 * np.sin(x[t - 2])) + .25 * rng.normal()
    # All predeclared lags, not the generating lag, are supplied to the independent test.
    return {'x': x[200:].tolist(), 'y': y[200:].tolist(), 'source_lags': [1, 2, 3, 4]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true'); parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--config', type=Path)
    args = parser.parse_args(argv)
    demo = settings(args.config)['demo']
    payload = demo_arrays(demo['m3_seed'], demo['m3_length']) if args.demo else read_json(args.input) if args.input else None
    if payload is None: parser.error('Use --demo or --input')
    output = args.output or (Path('causal_discovery/results/independent/m3_demo.json') if args.demo else None)
    result = test_granger(payload['x'], payload['y'], payload.get('source_lags'), self_lags=payload.get('self_lags'),
                          primary_lag=payload.get('primary_lag'), source=payload.get('source', 'X'), target=payload.get('target', 'Y'),
                          steps=payload.get('steps'), config=args.config or payload.get('config'),
                          artifact_dir=output.with_suffix('') if output else None)
    emit(result, output)
    if output: print(str(output))


if __name__ == '__main__': main()
