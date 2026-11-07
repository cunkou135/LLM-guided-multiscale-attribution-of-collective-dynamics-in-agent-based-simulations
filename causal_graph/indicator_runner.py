"""Steps 7–8: fail-closed execution and observation validity (no relation tests)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from dataclasses import replace

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype, is_complex_dtype, is_bool_dtype
from simulations.common.trajectory_api import Trajectory

from .io import digest, now, read_json, save_json
from .schemas import code_errors


class ReviewRejected(PermissionError):
    pass


def check_result(result, run_id, indicator_id, allowed_steps, settings, *, allow_undefined_entities=False):
    if isinstance(result, pd.Series):
        result = result.to_frame(name='value')
    if not isinstance(result, pd.DataFrame) or result.empty:
        raise ValueError('Output must be a nonempty Pandas Series/DataFrame')
    result = result.copy()
    entity_fields = []
    if isinstance(result.index, pd.MultiIndex):
        names = list(result.index.names)
        if 'step' not in names or any(not isinstance(n, str) or not n for n in names) or len(names) != len(set(names)):
            raise ValueError('MultiIndex requires uniquely named levels including step')
        entity_fields = [n for n in names if n != 'step']
        result = result.reset_index()
    if 'step' in result.columns:
        if result.index.name == 'step':
            raise ValueError('Ambiguous time: both step index and column')
        steps = result.pop('step')
        if not entity_fields:
            entity_fields = [n for n in ('agent_id', 'group_id', 'event_id') if n in result.columns]
    elif result.index.name == 'step':
        steps = pd.Series(result.index.to_numpy())
    else:
        raise ValueError('Output must have an explicit step column or index named step')
    if (not is_numeric_dtype(steps) or is_bool_dtype(steps) or is_complex_dtype(steps) or
            steps.isna().any() or not np.isfinite(steps.to_numpy()).all() or
            not (steps.to_numpy() == np.floor(steps.to_numpy())).all()):
        raise ValueError('Time indices must be finite integral steps')
    times = steps.to_numpy(dtype=np.int64)
    if not set(times.tolist()) <= set(allowed_steps):
        raise ValueError('Output includes unrecorded time steps')
    entity_keys = None
    if entity_fields:
        entities = result[entity_fields]
        if entities.isna().any().any():
            raise ValueError('Missing entity identifier')
        entity_keys = [json.dumps(dict(zip(entity_fields, row)), sort_keys=True, ensure_ascii=False, allow_nan=False,
                                  default=lambda value: value.item())
                       for row in entities.itertuples(index=False, name=None)]
        result = result.drop(columns=entity_fields)
    keys = pd.DataFrame({'step': times, 'entity': entity_keys if entity_keys is not None else ''})
    if keys.duplicated().any():
        raise ValueError('Duplicate time index within the same entity')
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
        series = result[column].reset_index(drop=True)
        finite = int(series.notna().sum())
        missing = float(series.isna().mean())
        constant = bool(series.nunique(dropna=True) <= 1 and finite > 0)
        minimum = finite
        undefined_entities = 0
        if entity_keys is not None:
            per_entity = series.notna().groupby(entity_keys).sum()
            minimum = int(per_entity.min())
            undefined_entities = int(per_entity.eq(0).sum())
            checked_minimum = int(per_entity.loc[per_entity.gt(0)].min()) if per_entity.gt(0).any() else 0
        else: checked_minimum = minimum
        columns[column] = {'finite_observations': finite, 'minimum_observations_per_entity': minimum,
                           'missing_fraction': missing, 'constant': constant,
                           'entities_without_defined_values': undefined_entities}
        required_minimum = checked_minimum if allow_undefined_entities else minimum
        if required_minimum < settings.min_observations:
            raise ValueError(f'{column}: insufficient actual observations ({required_minimum} < {settings.min_observations})')
        if constant:
            warnings.append(f'{column}: constant series; retained without causal claims')
        if missing > settings.missing_fraction_warning:
            warnings.append(f'{column}: high missing fraction {missing:.3f}')
    order = keys.sort_values(['step', 'entity'], kind='stable').index.to_numpy()
    result = result.astype(float).iloc[order].reset_index(drop=True)
    times = times[order]
    sorted_entities = np.asarray(entity_keys)[order] if entity_keys is not None else None
    pieces = []
    for column in result:
        frame = pd.DataFrame({'step': times, 'feature': column, 'value': result[column].to_numpy()})
        if sorted_entities is not None:
            frame.insert(1, 'entity_id', sorted_entities)
        pieces.append(frame)
    long = pd.concat(pieces, ignore_index=True)
    long.insert(0, 'indicator_id', indicator_id)
    long.insert(0, 'run_id', run_id)
    return long, {'rows': len(result), 'time_steps': int(len(set(times))),
                  'entity_fields': entity_fields, 'entities': len(set(entity_keys)) if entity_keys is not None else 1,
                  'columns': columns, 'warnings': warnings, 'start_step': int(times.min()),
                  'end_step': int(times.max()), 'observed_steps': sorted(set(times.tolist()))}


def load_approvals(path):
    if path is None:
        return None
    root = read_json(path)
    required = {'reviewer', 'reviewed_at', 'notes', 'code_sha256'}
    if not isinstance(root, dict) or not required <= set(root) or set(root) - required - {'rejections'}:
        raise ValueError('Review file requires reviewer, reviewed_at, notes, code_sha256')
    if any(not isinstance(root[k], str) or not root[k].strip() for k in ('reviewer', 'reviewed_at', 'notes')):
        raise ValueError('Review identity/date/notes cannot be empty')
    hashes = root['code_sha256']
    if not isinstance(hashes, dict) or any(not isinstance(k, str) or not isinstance(v, str) or
                                         len(v) != 64 or any(ch not in '0123456789abcdef' for ch in v) for k, v in hashes.items()):
        raise ValueError('Review code_sha256 must map indicator IDs to SHA-256 strings')
    rejections = root.get('rejections', {})
    if not isinstance(rejections, dict) or set(rejections) & set(hashes):
        raise ValueError('Rejected and approved indicator IDs must be disjoint mappings')
    for iid, review in rejections.items():
        if (not isinstance(iid, str) or not isinstance(review, dict) or set(review) != {'reason', 'code_sha256'} or
                not isinstance(review['reason'], str) or not review['reason'].strip() or
                not isinstance(review['code_sha256'], str) or len(review['code_sha256']) != 64 or
                any(c not in '0123456789abcdef' for c in review['code_sha256'])):
            raise ValueError('Each rejection requires a reason and exact code SHA-256')
    return root


def _trusted_compute(trajectory, node, code_file, settings, folder):
    """Reviewed-only subprocess; explicitly NOT a sandbox. No API credentials passed."""
    request = folder / 'worker_request.json'
    output = folder / 'returned_result.parquet'
    save_json(request, {'run_dir': str(trajectory.directory.resolve()), 'code_file': str(code_file.resolve()),
                        'code_sha256': node['code_sha256'], 'required': node['required'],
                        'config': node['config'], 'output': str(output),
                        'analysis_contract': node.get('analysis_contract'),
                        'step_batch_size': settings.execution_step_batch_size})
    keep = {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA',
            'APPDATA', 'PROGRAMDATA', 'CONDA_PREFIX', 'VIRTUAL_ENV'}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    command = [sys.executable, '-m', 'causal_graph.trusted_worker', str(request.resolve())]
    save_json(folder / 'process.json', {'command': command, 'timeout_seconds': settings.indicator_timeout,
                                       'started_at': now(), 'mode': 'reviewed_local_subprocess'})
    with (folder / 'stdout.log').open('wb') as stdout, (folder / 'stderr.log').open('wb') as stderr:
        try:
            proc = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env,
                                  stdout=stdout, stderr=stderr, timeout=settings.indicator_timeout)
        except subprocess.TimeoutExpired:
            save_json(folder / 'process_result.json', {'status': 'timeout', 'ended_at': now()})
            raise
    save_json(folder / 'process_result.json', {'returncode': proc.returncode, 'ended_at': now()})
    if proc.returncode:
        raise RuntimeError((folder / 'stderr.log').read_text(encoding='utf-8', errors='replace')[-3000:])
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
    report['execution_started'] = False
    started = time.monotonic()
    try:
        if node.get('implementation_status') == 'unavailable':
            raise LookupError('Definition retained but implementation unavailable: ' + node['failure_reason'])
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
            adapter = folder / 'execution_adapter.py'
            adapter.write_text(code.read_text(encoding='utf-8') + '\n\n_stage1_original = compute_indicator\n'
                'def compute_indicator(data, config):\n'
                f'    required = {node["required"]!r}\n'
                '    projected = {name: data[name].loc[:, fields].copy(deep=True) for name, fields in required.items()}\n'
                '    return _stage1_original(projected, config)\n', encoding='utf-8')
            report['execution_adapter_sha256'] = digest(adapter)
            result = trajectory.compute_isolated(adapter, node['required'], node['config'],
                                                  image=settings.image, timeout=settings.indicator_timeout)
        else:
            rejection = (approvals or {}).get('rejections', {}).get(iid)
            if rejection is not None:
                if rejection['code_sha256'] != node['code_sha256']:
                    raise PermissionError('Rejection review does not match current code SHA-256')
                raise ReviewRejected(rejection['reason'])
            if approvals is None or approvals['code_sha256'].get(iid) != node['code_sha256']:
                raise PermissionError('Explicit code review with matching code SHA-256 required')
            report['code_review'] = {k: approvals[k] for k in ('reviewer', 'reviewed_at', 'notes')}
            report['execution_started'] = True
            result = _trusted_compute(trajectory, node, code, settings, folder)
        # Keep returned data even when numerical/time validation subsequently fails.
        if isinstance(result, pd.Series):
            result = result.to_frame(name='value')
        if isinstance(result, pd.DataFrame):
            result.to_parquet(folder / 'returned_result.parquet')
        contract = node.get('analysis_contract', {})
        aggregation = contract.get('mapping', {}).get('kind') == 'entity_aggregate'
        raw_settings = replace(settings, min_observations=1) if aggregation else settings
        series, quality = check_result(result, rid, iid, run['allowed_steps'], raw_settings, allow_undefined_entities=aggregation)
        quality['raw_observation_validation'] = {'minimum_per_observed_entity':raw_settings.min_observations,
            'undefined_entities_allowed_for_declared_aggregation':aggregation,
            'analysis_time_eligibility':'separately checked by M1 after the predeclared mapping'}
        destination = Path(root) / 'indicator_series' / rid / f'{iid}.parquet'
        destination.parent.mkdir(parents=True, exist_ok=True)
        series.to_parquet(destination, index=False)
        report.update(status='success', series_file=destination.relative_to(root).as_posix(),
                      series_sha256=digest(destination), quality=quality)
    except Exception as exc:
        kind = 'review_rejected' if isinstance(exc, ReviewRejected) else 'unavailable_data' if isinstance(exc, LookupError) else 'review_required' if isinstance(exc, PermissionError) else 'execution_or_validation_error'
        report.update(error_type=kind, error=f'{type(exc).__name__}: {exc}')
    report.update(ended_at=now(), elapsed_seconds=time.monotonic() - started)
    save_json(folder / 'report.json', report)
    return report
