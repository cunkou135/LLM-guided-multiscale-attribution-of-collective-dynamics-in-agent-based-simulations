"""Exact registered scenario matching and unchanged-model simulation preparation."""
from copy import deepcopy
from pathlib import Path

import yaml

from causal_graph.inputs import assert_unchanged, inspect_run
from causal_graph.io import digest, object_digest, read_json, save_json
from causal_discovery._common import align_runs, make_windows
from scenarios.protocol import load_scenario
from simulations.common import runner
from simulations.common.trajectory_api import Trajectory

ROOT = Path(__file__).resolve().parents[1]


def match_scenario(path: str | Path) -> dict:
    fingerprint = digest(path)
    registry = yaml.safe_load((ROOT / 'scenarios/manifest.yaml').read_text(encoding='utf-8'))['scenarios']
    for sid, entry in registry.items():
        for version, item in entry['versions'].items():
            if fingerprint == item['sha256']:
                if sid not in ('SCENARIO-FISH-001', 'SCENARIO-COVASIM-001'):
                    raise ValueError(f'Registered model not supported by full_pipeline: {sid}')
                result = load_scenario(sid, version=version)
                result['model'] = 'fish' if sid == 'SCENARIO-FISH-001' else 'covasim'
                return result
    raise ValueError('Unsupported scenario: exact registered scenario SHA-256 required; no similar-model substitution')


def source_identity(model: str) -> dict:
    files = list((ROOT / 'simulations' / model).rglob('*.py'))
    files += list((ROOT / 'simulations/common').glob('*.py'))
    if model == 'covasim': files += list((ROOT / 'native_covasim').rglob('*.py'))
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(set(files))}


def simulation_config(scenario: dict, config: dict, seed: int, output: Path) -> dict:
    model = scenario['model']; cfg = runner.load(ROOT / config['configs'][model])
    if cfg['model'] != model or cfg['scenario_id'] != scenario['scenario_id']:
        raise ValueError('Registered scenario and simulation config differ')
    cfg = deepcopy(cfg)
    cfg.update(scenario_version=scenario['scenario_version'], seed=seed)
    if config['steps'][model] is not None: cfg['steps'] = config['steps'][model]
    cfg['sampling']['frequency'] = config['sampling_frequency']
    cfg['output']['directory'] = str(output.resolve())
    cfg['visualization']['enabled'] = False
    if model == 'covasim': cfg['engine']['python'] = str((ROOT / cfg['engine']['python']).resolve())
    runner.validate(cfg)
    return cfg


def prepare_run(scenario: dict, cfg: dict, cache: Path, reuse: bool, run_function=runner.run) -> dict:
    identity = {k: v for k, v in cfg.items() if k not in ('output', 'visualization')}
    identity.update(scenario_sha256=scenario['scenario_sha256'], sources=source_identity(scenario['model']))
    key = object_digest(identity); cached = cache / f'{key}.json'
    if reuse and cached.exists():
        saved = read_json(cached)
        if saved['identity'] != identity: raise ValueError('Simulation cache identity mismatch')
        assert_unchanged([saved])
        return {**saved, 'reused': True}
    output = Path(run_function(cfg)).resolve(); inspected = inspect_run(output)
    actual = inspected['manifest']
    for key_name in ('model_version', 'seed', 'parameters', 'sampling', 'logging'):
        if actual.get(key_name) != cfg[key_name]: raise ValueError(f'Runner changed requested {key_name}')
    if actual['scenario_sha256'] != scenario['scenario_sha256'] or actual['requested_steps'] != cfg['steps']:
        raise ValueError('Runner scenario/time budget differs from requested config')
    saved = {'identity': identity, 'directory': str(output), 'data_hashes': inspected['data_hashes'],
             'run_id': actual['run_id'], 'seed': actual['seed'], 'reused': False, 'inspection': inspected}
    save_json(cached, saved)
    return saved


def coverage_report(run_records: list[dict], discovery_config: dict) -> dict:
    """Check raw recorded clock coverage only, without inventing indicator observations."""
    clocks = {r['run_id']: Trajectory(r['directory']).available_steps() for r in run_records}
    arrays, _ = align_runs(clocks, steps=clocks)
    windows = make_windows(arrays, discovery_config)
    counts = windows['split_report']['windows']
    return {'scope': 'recorded clock coverage only, not indicator validity or statistical power',
            'sufficient_clock_coverage': all(counts[k] >= v for k, v in discovery_config['split']['min_windows'].items()) and
                sum(map(len, clocks.values())) >= discovery_config['data']['min_total_observations'],
            'partition_windows': counts, 'run_count': len(clocks), 'split': windows['split_report']}
