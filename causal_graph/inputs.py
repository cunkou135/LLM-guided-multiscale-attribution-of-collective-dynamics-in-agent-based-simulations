"""Step 1: validate completed runs using public Trajectory and scenario APIs."""
from pathlib import Path
from pandas.api.types import is_integer_dtype
import pyarrow as pa

from scenarios.protocol import load_scenario
from simulations.common.trajectory_api import Trajectory

from .io import digest, read_json


def resolve_runs(run_dirs=(), run_ids=(), runs_root='results'):
    paths = [Path(p).resolve() for p in run_dirs] + [(Path(runs_root) / r).resolve() for r in run_ids]
    if not paths or len(set(paths)) != len(paths):
        raise ValueError('Provide one or more distinct run directories or run IDs')
    root = Path(runs_root).resolve()
    if any(Path(r).name != r for r in run_ids) or any(not p.is_relative_to(root) for p in paths[len(run_dirs):]):
        raise ValueError('run_id must be a simple child directory name')
    return paths


def inspect_run(path):
    path = Path(path).resolve()
    needed = ('manifest.json', 'scenario.md', 'resolved_config.yaml', 'field_catalog.json')
    for name in needed:
        if not (path / name).is_file():
            raise ValueError(f'Incomplete run: missing {name} in {path}')
    t = Trajectory(path)
    meta, cfg = t.metadata(), t.configuration()
    if not isinstance(meta, dict) or not isinstance(cfg, dict):
        raise ValueError('Manifest and configuration must be mappings')
    if meta.get('status') not in {'max_steps', 'stable', 'frozen', 'all_happy'} or meta.get('error'):
        raise ValueError(f'Run is not successfully completed: {meta.get("status")}')
    required_meta = ('run_id', 'model_name', 'model_version', 'scenario_id', 'scenario_version', 'scenario_sha256',
                     'actual_steps', 'seed', 'checksums_sha256')
    if any(k not in meta for k in required_meta):
        raise ValueError('Incomplete manifest provenance')
    if type(meta['actual_steps']) is not int or meta['actual_steps'] < 0:
        raise ValueError('Invalid completed time range')
    if (not isinstance(meta['run_id'], str) or not meta['run_id'] or
            any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for ch in meta['run_id'])):
        raise ValueError('Unsafe run_id')
    model = meta['model_name']
    expected_scenario = ('SCENARIO-FISH-001' if model == 'fish' else 'SCENARIO-COVASIM-001' if model == 'covasim'
                         else 'SCENARIO-SCHELLING-001' if model.startswith('schelling') else None)
    if expected_scenario is None or meta['scenario_id'] != expected_scenario:
        raise ValueError('Model/scenario identity mismatch')
    scenario = load_scenario(meta['scenario_id'], version=meta['scenario_version'])
    if digest(path / 'scenario.md') != scenario['scenario_sha256'] or meta['scenario_sha256'] != scenario['scenario_sha256']:
        raise ValueError('Fixed scenario hash mismatch')
    checks = {'model': 'model_name', 'model_version': 'model_version', 'scenario_id': 'scenario_id', 'seed': 'seed'}
    if any(cfg.get(a) != meta[b] for a, b in checks.items()) or cfg.get('scenario_version', '1.0') != meta['scenario_version']:
        raise ValueError('Resolved configuration/manifest mismatch')
    if cfg.get('parameters') != meta.get('parameters'):
        raise ValueError('Resolved parameter provenance mismatch')
    checksums = meta['checksums_sha256']
    if not isinstance(checksums, dict) or not checksums:
        raise ValueError('Missing source checksums')
    for name, expected in checksums.items():
        file = path / name
        if not isinstance(name, str) or Path(name).name != name or not file.is_file() or digest(file) != expected:
            raise ValueError(f'Run data hash mismatch or missing file: {name}')
    if not {'model_states', 'agent_states'} <= set(t.catalog):
        raise ValueError('Raw agent_states and model_states are required')
    actual_hashes = t.source_fingerprints()
    if any(checksums.get(k) != v for k, v in actual_hashes.items()):
        raise ValueError('Unregistered or changed Parquet input')
    rows = {}
    time_steps = set()
    for name, entry in t.catalog.items():
        if name not in {'agent_states', 'events', 'contacts', 'raw_frames', 'model_states'} or name + '.parquet' not in checksums:
            raise ValueError(f'Invalid or unregistered catalog table: {name}')
        columns = list(t.table_schema(name).names)
        if set(columns) != set(entry['fields']):
            raise ValueError(f'Catalog/Parquet field mismatch: {name}')
        if 'step' not in columns or not pa.types.is_integer(t.table_schema(name).field('step').type):
            raise ValueError(f'Invalid source time coordinate type: {name}')
        keys = ('run_id', 'model_name', 'model_version', 'scenario_id', 'scenario_version', 'scenario_sha256', 'seed')
        if not set(keys) | {'step'} <= set(columns): raise ValueError(f'Missing provenance fields: {name}')
        rows[name] = 0
        seen_model_steps = set()
        for batch in t.iter_batches(name, columns=[*keys, 'step']):
            data = batch.to_pandas(); rows[name] += len(data)
            for key in keys:
                if not data[key].eq(meta[key]).all(): raise ValueError(f'Row provenance mismatch: {name}/{key}')
            if not is_integer_dtype(data.step) or data.step.isna().any() or not data.step.between(0, meta['actual_steps']).all():
                raise ValueError(f'Invalid source time bounds: {name}')
            values = set(int(s) for s in data.step.unique())
            if name == 'model_states':
                if data.step.duplicated().any() or seen_model_steps & values: raise ValueError('Duplicate model-state time indices')
                seen_model_steps.update(values)
            time_steps.update(values)
    steps = t.available_steps()
    if not steps or steps[0] != 0 or steps[-1] != meta['actual_steps'] or not rows['agent_states']:
        raise ValueError('Missing initial/final source snapshots or empty agent states')
    provenance_files = set(needed) | set(checksums) | set(actual_hashes)
    return {'directory': str(path), 'manifest': meta, 'rows': rows, 'snapshot_steps': steps,
            'allowed_steps': sorted(time_steps), 'data_hashes': {n: digest(path / n) for n in sorted(provenance_files)},
            'scenario_text': (path / 'scenario.md').read_text(encoding='utf-8'), 'scenario': {k: v for k, v in scenario.items() if k != 'text'}}


def inspect_runs(paths):
    if not paths:
        raise ValueError('Provide at least one completed input run')
    runs = [inspect_run(path) for path in paths]
    keys = ('model_name', 'model_version', 'scenario_id', 'scenario_version', 'scenario_sha256')
    identity = tuple(runs[0]['manifest'][k] for k in keys)
    if any(tuple(r['manifest'][k] for k in keys) != identity for r in runs):
        raise ValueError('All runs must have the same model and fixed scenario version/hash')
    if len({r['manifest']['run_id'] for r in runs}) != len(runs):
        raise ValueError('Duplicate input run_id')
    return runs


def assert_unchanged(runs):
    for run in runs:
        for name, expected in run['data_hashes'].items():
            if digest(Path(run['directory']) / name) != expected:
                raise ValueError(f'Input changed during execution: {name}')
