"""Small CPU GRU shared implementation; no dependency on any m-module."""
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
from torch import nn

from ._common import TARGET, align_runs, make_windows, serializable, sha256


class SmallGRU(nn.Module):
    def __init__(self, inputs: int, outputs: int, hidden: int):
        super().__init__()
        self.gru = nn.GRU(inputs, hidden, batch_first=True)
        self.readout = nn.Sequential(nn.Linear(hidden, hidden), nn.Tanh(), nn.Linear(hidden, outputs))

    def forward(self, x):
        states, _ = self.gru(x)  # Hidden states are never interpreted as delays.
        return self.readout(states[:, -1])


def prepare(y: Any, parents: Mapping[str, Any], steps: Any, cfg: dict) -> dict:
    runs, _ = align_runs(y, parents, steps)
    data = make_windows(runs, cfg)
    inadequate = {role: len(g['y']) for role, g in data['groups'].items()
                  if len(g['y']) < cfg['split']['min_windows'][role]}
    data['inadequate'] = inadequate
    if inadequate: return data
    train = data['groups']['train']
    mean_x = train['x'].mean(axis=(0, 1), keepdims=True)
    scale_x = train['x'].std(axis=(0, 1), keepdims=True)
    scale_x = np.where(scale_x > 1e-7, scale_x, 1.0)
    mean_y = train['y'].mean(axis=0, keepdims=True)
    scale_y = train['y'].std(axis=0, keepdims=True)
    if not np.all(scale_y > 1e-7): raise ValueError('Constant training target has no estimable dynamics')
    data['normalization'] = {'mean_x': mean_x.tolist(), 'scale_x': scale_x.tolist(),
                              'mean_y': mean_y.tolist(), 'scale_y': scale_y.tolist(), 'fit_partition': 'train only'}
    for group in data['groups'].values():
        group['x_scaled'] = ((group['x'] - mean_x) / scale_x).astype(np.float32)
        group['y_scaled'] = ((group['y'] - mean_y) / scale_y).astype(np.float32)
    return data


def input_mask(data: dict, lags: Mapping[str, list[int]] | None = None) -> np.ndarray:
    shape = (data['max_lag'], data['groups']['train']['x'].shape[-1])
    if lags is None: return np.ones(shape, dtype=np.float32)
    mask = np.zeros(shape, dtype=np.float32)
    for name, physical_lags in lags.items():
        if name not in data['slices']: raise ValueError(f'Unknown input variable: {name}')
        begin, end = data['slices'][name]
        for lag in physical_lags:
            if type(lag) is not int or lag <= 0 or lag % data['step_size']:
                raise ValueError('Lags must be positive integer multiples of the recorded step interval')
            sampled = lag // data['step_size']
            if sampled > data['max_lag']: raise ValueError('Lag exceeds configured history')
            mask[-sampled, begin:end] = 1
    return mask


def fit(data: dict, mask: np.ndarray, cfg: dict, seed: int, artifact: Path | None = None) -> tuple[SmallGRU, dict]:
    torch.set_num_threads(cfg['rnn']['threads'])
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    r = cfg['rnn']; train, validation = (data['groups'][k] for k in ('train', 'validation'))
    model = SmallGRU(train['x'].shape[-1], train['y'].shape[-1], r['hidden_size'])
    optimizer = torch.optim.Adam(model.parameters(), lr=r['learning_rate'], weight_decay=r['weight_decay'])
    x = torch.from_numpy(train['x_scaled'] * mask); y = torch.from_numpy(train['y_scaled'])
    vx = torch.from_numpy(validation['x_scaled'] * mask); vy = torch.from_numpy(validation['y_scaled'])
    rng = np.random.default_rng(seed)
    history, best, best_epoch, wait, state = [], float('inf'), 0, 0, None
    for epoch in range(r['epochs']):
        model.train()
        for batch in np.array_split(rng.permutation(len(x)), max(1, int(np.ceil(len(x) / r['batch_size'])))):
            batch_x = x[batch]
            if r['input_dropout']:
                batch_x = batch_x * (torch.rand_like(batch_x) >= r['input_dropout'])
            optimizer.zero_grad(set_to_none=True)
            loss = torch.mean((model(batch_x) - y[batch]) ** 2)
            if not torch.isfinite(loss): raise ValueError('RNN training diverged')
            loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), r['gradient_clip_norm']); optimizer.step()
        model.eval()
        with torch.no_grad():
            training_loss = float(torch.mean((model(x) - y) ** 2))
            validation_loss = float(torch.mean((model(vx) - vy) ** 2))
        history.append({'epoch': epoch + 1, 'train_loss': training_loss, 'validation_loss': validation_loss})
        if validation_loss < best - 1e-7:
            best, best_epoch, wait = validation_loss, epoch + 1, 0
            state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else: wait += 1
        if epoch + 1 >= r['min_epochs'] and wait >= r['patience']: break
    model.load_state_dict(state); model.eval()
    card = {'seed': seed, 'architecture': {'type': 'GRU', 'input_size': x.shape[-1], 'hidden_size': r['hidden_size'],
                                          'output_size': y.shape[-1], 'layers': 1, 'readout': 'linear-tanh-linear'},
            'parameter_count': sum(p.numel() for p in model.parameters()), 'best_epoch': best_epoch,
            'epochs_run': len(history), 'max_epochs': r['epochs'], 'history': history, 'normalization': data['normalization'],
            'input_mask': mask.tolist(), 'config': r, 'device': 'cpu', 'torch_version': str(torch.__version__),
            'threads': r['threads'], 'gradient_clip_norm': r['gradient_clip_norm']}
    if artifact:
        artifact = Path(artifact); artifact.parent.mkdir(parents=True, exist_ok=True)
        torch.save({'state_dict': state, 'model_card': card}, artifact)
        card.update(parameter_file=str(artifact.resolve()), parameter_sha256=sha256(artifact))
    else:
        card['model_parameters'] = {k: v.tolist() for k, v in state.items()}
    return model, serializable(card)


def losses(model: SmallGRU, group: dict, mask: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        prediction = model(torch.from_numpy(group['x_scaled'] * mask)).numpy()
    return np.mean((prediction - group['y_scaled']) ** 2, axis=1)


def by_run(values: np.ndarray, group: dict) -> dict[str, np.ndarray]:
    names = np.asarray(group['run_ids'])
    return {name: values[names == name] for name in dict.fromkeys(group['run_ids'])}


def average_run_score(values: np.ndarray, group: dict) -> float:
    return float(np.mean([v.mean() for v in by_run(values, group).values()]))
