"""Steps 7–8: fail-closed execution and observation validity (no relation tests)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype, is_complex_dtype, is_bool_dtype
from simulations.common.trajectory_api import Trajectory

from .io import digest, now, read_json, save_json
from .schemas import code_errors


def check_result(result, run_id, indicator_id, allowed_steps, settings):
    if isinstance(result, pd.Series):
        result = result.to_frame(name='value')
    if not isinstance(result, pd.DataFrame) or result.empty:
        raise ValueError('Output must be a nonempty Pandas Series/DataFrame')
    result = result.copy()
    if 'step' in result.columns:
        if result.index.name == 'step':
            raise ValueError('Ambiguous time: both step index and column')
        steps = result.pop('step')
    elif result.index.name == 'step':
        steps = pd.Series(result.index.to_numpy())
    else:
        raise ValueError('Output must have an explicit step column or index named step')
    if (not is_numeric_dtype(steps) or is_bool_dtype(steps) or is_complex_dtype(steps) or
            steps.isna().any() or not np.isfinite(steps.to_numpy()).all() or
            not (steps.to_numpy() == np.floor(steps.to_numpy())).all()):
        raise ValueError('Time indices must be finite integral steps')
    if steps.duplicated().any():
        raise ValueError('Duplicate time index')
    if not set(steps.tolist()) <= set(allowed_steps):
        raise ValueError('Output includes unrecorded time steps')
    if not result.columns.is_unique or len(result.columns) == 0:
        raise ValueError('Output needs unique numeric value columns')
    if any(not isinstance(c, str) or not c for c in result.columns):
        raise ValueError('Value column names must be nonempty strings')
    if any(not is_numeric_dtype(result[c]) or is_complex_dtype(result[c]) for c in result):
        raise ValueError('Non-numeric or complex indicator output')
    values = result.astype(float).to_numpy()
    if np.isinf(values).any():
        raise ValueError('Infinite indicator value')
    warnings, columns = [], {}
    for column in result:
        series = result[column]
        finite = int(series.notna().sum())
        missing = float(series.isna().mean())
        constant = bool(series.nunique(dropna=True) <= 1 and finite > 0)
        columns[column] = {'finite_observations': finite, 'missing_fraction': missing, 'constant': constant}
        if finite < settings.min_observations:
            raise ValueError(f'{column}: insufficient actual observations ({finite} < {settings.min_observations})')
        if constant:
            warnings.append(f'{column}: constant series; retained without causal claims')
        if missing > settings.missing_fraction_warning:
            warnings.append(f'{column}: high missing fraction {missing:.3f}')
    result = result.astype(float)
    result.index = steps.to_numpy(dtype=np.int64)
    result.index.name = 'step'
    result = result.sort_index()
    long = pd.concat([pd.DataFrame({'step': result.index.to_numpy(), 'feature': column,
                                    'value': result[column].to_numpy()}) for column in result], ignore_index=True)
    long.insert(0, 'indicator_id', indicator_id)
    long.insert(0, 'run_id', run_id)
    return long, {'rows': len(result), 'columns': columns, 'warnings': warnings,
                  'start_step': int(result.index.min()), 'end_step': int(result.index.max()),
                  'observed_steps': result.index.tolist()}


def load_approvals(path):
    if path is None:
        return None
    root = read_json(path)
    if not isinstance(root, dict) or set(root) != {'reviewer', 'reviewed_at', 'notes', 'code_sha256'}:
        raise ValueError('Review file requires reviewer, reviewed_at, notes, code_sha256')
    if any(not isinstance(root[k], str) or not root[k].strip() for k in ('reviewer', 'reviewed_at', 'notes')):
        raise ValueError('Review identity/date/notes cannot be empty')
    hashes = root['code_sha256']
    if not isinstance(hashes, dict) or any(not isinstance(k, str) or not isinstance(v, str) or
                                         len(v) != 64 or any(ch not in '0123456789abcdef' for ch in v) for k, v in hashes.items()):
        raise ValueError('Review code_sha256 must map indicator IDs to SHA-256 strings')
    return root


def _trusted_compute(trajectory, node, code_file, settings):
    """Reviewed-only subprocess; explicitly NOT a sandbox. No API credentials passed."""
    with tempfile.TemporaryDirectory(prefix='reviewed_indicator_') as tmp:
        request = Path(tmp) / 'request.json'
        output = Path(tmp) / 'result.parquet'
        save_json(request, {'run_dir': str(trajectory.directory.resolve()), 'code_file': str(code_file.resolve()),
                            'code_sha256': node['code_sha256'], 'required': node['required'],
                            'config': node['config'], 'output': str(output)})
        keep = {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA',
                'APPDATA', 'PROGRAMDATA', 'CONDA_PREFIX', 'VIRTUAL_ENV'}
        env = {k: v for k, v in os.environ.items() if k.upper() in keep}
        env.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
        proc = subprocess.run([sys.executable, '-m', 'causal_graph.trusted_worker', str(request)],
                              cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True,
                              timeout=settings.indicator_timeout)
        if proc.returncode:
            raise RuntimeError(proc.stderr.decode('utf-8', errors='replace')[-3000:])
        return pd.read_parquet(output)


def execute_indicator(node, run, root, settings, approvals=None):
    rid, iid = run['manifest']['run_id'], node['indicator_id']
    parent = Path(root) / 'execution' / rid / iid
    parent.mkdir(parents=True, exist_ok=True)
    folder = parent / f'attempt_{len(list(parent.glob("attempt_*"))):03d}'
    folder.mkdir(exist_ok=False)
    report = {'run_id': rid, 'indicator_id': iid, 'mode': settings.execution_mode,
              'code_sha256': node['code_sha256'], 'generation_call': node['generation_call'],
              'required': node['required'], 'started_at': now(), 'status': 'failed',
              'source_hashes': run['data_hashes']}
    started = time.monotonic()
    try:
        trajectory = Trajectory(run['directory'])
        for table, fields in node['required'].items():
            if table not in trajectory.catalog:
                raise LookupError(f'{table}: table was not recorded')
            missing = set(fields) - set(trajectory.catalog[table]['fields'])
            if missing:
                raise LookupError(f'{table}: missing fields {sorted(missing)}')
        code = Path(root) / node['code_file']
        if digest(code) != node['code_sha256'] or code_errors(code.read_text(encoding='utf-8')):
            raise ValueError('Generated code changed or failed structural review')
        # Required inputs were read from real tables. This does not prove semantic correctness
        # or absence of fabricated math in arbitrary code; human scientific review remains needed.
        report['data_contract_valid'] = True
        if settings.execution_mode == 'isolated':
            result = trajectory.compute_isolated(code, node['required'], node['config'],
                                                  image=settings.image, timeout=settings.indicator_timeout)
        else:
            if approvals is None or approvals['code_sha256'].get(iid) != node['code_sha256']:
                raise PermissionError('Explicit human review with matching code SHA-256 required')
            report['human_review'] = {k: approvals[k] for k in ('reviewer', 'reviewed_at', 'notes')}
            result = _trusted_compute(trajectory, node, code, settings)
        # Keep returned data even when numerical/time validation subsequently fails.
        if isinstance(result, pd.Series):
            result = result.to_frame(name='value')
        if isinstance(result, pd.DataFrame):
            result.to_parquet(folder / 'returned_result.parquet')
        series, quality = check_result(result, rid, iid, run['allowed_steps'], settings)
        destination = Path(root) / 'indicator_series' / rid / f'{iid}.parquet'
        destination.parent.mkdir(parents=True, exist_ok=True)
        series.to_parquet(destination, index=False)
        report.update(status='success', series_file=destination.relative_to(root).as_posix(),
                      series_sha256=digest(destination), quality=quality)
    except Exception as exc:
        kind = 'unavailable_data' if isinstance(exc, LookupError) else 'review_required' if isinstance(exc, PermissionError) else 'execution_or_validation_error'
        report.update(error_type=kind, error=f'{type(exc).__name__}: {exc}')
    report.update(ended_at=now(), elapsed_seconds=time.monotonic() - started)
    save_json(folder / 'report.json', report)
    return report
