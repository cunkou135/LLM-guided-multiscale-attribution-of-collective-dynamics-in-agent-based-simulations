import itertools
import copy
import json
import logging
import math
import platform
import random
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import mesa
import numpy
import pandas
import pyarrow
import yaml

from simulations.common.trajectory_api import TrajectoryWriter
from simulations.covasim.adapter import RemoteCovasim
from simulations.schelling.model import Schelling
from simulations.schelling.extended import ExtendedSchelling
from scenarios.protocol import load_scenario


def load(path):
    with open(path, encoding='utf-8') as handle:
        config = yaml.safe_load(handle)
    validate(config)
    return config


def validate(c):
    required = {'model', 'model_version', 'scenario_id', 'seed', 'steps', 'parameters', 'sampling', 'logging', 'output', 'visualization'}
    if not isinstance(c, dict) or set(c) - {'engine', 'scenario_version'} != required:
        raise ValueError(f'configuration keys must be {sorted(required)}')
    if (c['model'], c['model_version']) not in (('schelling', '1'), ('schelling_standard', '1'), ('schelling_extended', '2.0'), ('covasim', '2.0.0'), ('fish','fish-3.0')):
        raise ValueError('unsupported model or version')
    if c['scenario_id'] != ('SCENARIO-SCHELLING-001' if c['model'].startswith('schelling') else 'SCENARIO-FISH-001' if c['model']=='fish' else 'SCENARIO-COVASIM-001'):
        raise ValueError('model and fixed scenario do not match')
    if type(c['seed']) is not int or not 0 <= c['seed'] < 2**32 or type(c['steps']) is not int or c['steps'] < 1:
        raise ValueError('seed and steps must be nonnegative integer and positive integer')
    if not isinstance(c['sampling'], dict) or set(c['sampling']) != {'frequency'} or type(c['sampling']['frequency']) is not int or c['sampling']['frequency'] < 1:
        raise ValueError('sampling.frequency must be a positive integer')
    log = c['logging']
    expected_log = {'format', 'batch_size', 'compression', 'agent_states', 'events', 'model_states', 'level'} | ({'contacts'} if c['model'] in ('covasim','fish') else set())
    if not isinstance(log, dict) or set(log) != expected_log or log.get('format') != 'parquet':
        raise ValueError('invalid logging fields')
    if type(log['batch_size']) is not int or log['batch_size'] < 1 or log['compression'] not in ('zstd', 'snappy', 'gzip', 'none') or log['level'] not in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
        raise ValueError('invalid logging batch size, compression or level')
    if any(type(log[k]) is not bool for k in ('agent_states', 'events', 'model_states')):
        raise ValueError('logging data switches must be booleans')
    if not isinstance(c['output'], dict) or set(c['output']) != {'directory'} or not isinstance(c['output']['directory'], str) or not c['output']['directory']:
        raise ValueError('output.directory required')
    v = c['visualization']
    if not isinstance(v, dict) or set(v) - {'display'} != {'enabled', 'host', 'port'} or type(v['enabled']) is not bool or not isinstance(v['host'], str) or not v['host'] or type(v['port']) is not int or not 1 <= v['port'] <= 65535:
        raise ValueError('visualization requires enabled, host and port')
    p = c['parameters']
    if not isinstance(p, dict):
        raise ValueError('parameters must be a mapping')
    number = lambda x: type(x) in (int, float) and math.isfinite(x)
    if 'display' in v:
        display = v['display']
        if not isinstance(display, dict) or set(display) - {'play_interval_seconds', 'recent_steps', 'figure_config', 'population_config','fish_config'}:
            raise ValueError('invalid visualization.display fields')
        if not number(display.get('play_interval_seconds', .35)) or display.get('play_interval_seconds', .35) <= 0:
            raise ValueError('play interval must be positive')
        if type(display.get('recent_steps', 3)) is not int or display.get('recent_steps', 3) < 0:
            raise ValueError('recent_steps must be a nonnegative integer')
        if not isinstance(display.get('figure_config', 'configs/figures.yaml'), str):
            raise ValueError('figure_config must be a path')
        if not isinstance(display.get('population_config', 'configs/population.yaml'), str):
            raise ValueError('population_config must be a path')
    if c['model'].startswith('schelling'):
        extended = c['model'] == 'schelling_extended'
        extra = {'homophily_mean', 'homophily_std', 'homophily_min', 'homophily_max', 'relocation_radius', 'relocation_policy'} if extended else {'homophily'}
        if set(p) != {'width', 'height', 'density', 'minority_pc', 'radius', 'torus'} | extra:
            raise ValueError('invalid Schelling parameters')
        if any(type(p[k]) is not int or p[k] < 2 for k in ('width', 'height')) or type(p['radius']) is not int or p['radius'] < 1 or type(p['torus']) is not bool:
            raise ValueError('invalid grid dimensions, radius or torus')
        if any(not number(p[k]) or not 0 <= p[k] <= 1 for k in ('density', 'minority_pc') + (() if extended else ('homophily',))):
            raise ValueError('probabilities must lie within [0, 1]')
        if extended:
            from statistics import NormalDist
            if p['radius'] != 1 or type(p['relocation_radius']) is not int or p['relocation_radius'] < 1 or p['relocation_policy'] != 'best_local_satisfactory':
                raise ValueError('extended model requires Moore radius 1 and positive relocation radius')
            if any(not number(p[k]) for k in ('homophily_mean', 'homophily_std', 'homophily_min', 'homophily_max')) or not 0 <= p['homophily_min'] < p['homophily_max'] <= 1 or p['homophily_std'] < 0:
                raise ValueError('invalid truncated normal parameters')
            if p['homophily_std'] == 0:
                if not p['homophily_min'] <= p['homophily_mean'] <= p['homophily_max']:
                    raise ValueError('degenerate preference lies outside bounds')
            else:
                distribution = NormalDist(p['homophily_mean'], p['homophily_std'])
                if distribution.cdf(p['homophily_max']) - distribution.cdf(p['homophily_min']) < 1e-8:
                    raise ValueError('truncation acceptance probability too small for rejection sampling')
    elif c['model']=='fish':
        from simulations.fish.adapter import validate_parameters
        validate_parameters(p)
        if type(log['contacts']) is not bool:
            raise ValueError('logging.contacts must be boolean')
    else:
        if c['steps'] < 2:
            raise ValueError('Covasim 2.0.0 requires steps >= 2 (native n_days must be positive)')
        if set(p) != {'pop_size', 'pop_infected', 'pop_type', 'start_day', 'beta', 'pop_scale', 'rescale', 'interventions'}:
            raise ValueError('invalid Covasim parameters')
        if type(p['pop_size']) is not int or p['pop_size'] < 2 or type(p['pop_infected']) is not int or not 0 <= p['pop_infected'] <= p['pop_size']:
            raise ValueError('invalid Covasim population')
        if p['pop_type'] != 'hybrid' or not number(p['beta']) or not 0 <= p['beta'] <= 1 or p['pop_scale'] != 1 or p['rescale'] is not False:
            raise ValueError('current uncalibrated profile requires hybrid, pop_scale=1 and rescale=false')
        from datetime import date
        date.fromisoformat(p['start_day'])
        if not isinstance(p['interventions'], list) or any(not isinstance(i, dict) or i.get('type') not in ('test_prob', 'contact_tracing', 'change_beta', 'clip_edges') for i in p['interventions']):
            raise ValueError('invalid intervention definitions')
        engine = c.get('engine')
        if not isinstance(engine, dict) or set(engine) != {'python', 'experiment_class'} or not isinstance(engine['python'], str) or engine['experiment_class'] != 'uncalibrated_demonstration':
            raise ValueError('Covasim requires explicit interpreter and uncalibrated_demonstration classification')
        if type(log['contacts']) is not bool:
            raise ValueError('logging.contacts must be boolean')


class RunSession:
    """Identical lifecycle used by batch, headless and interactive execution."""
    def __init__(self, c, live_snapshots=False):
        validate(c)
        self.config = c
        logging.getLogger('abms_lab').setLevel(c['logging']['level'])
        self.meta = dict(run_id=uuid.uuid4().hex, model_name=c['model'], model_version=c['model_version'], seed=c['seed'])
        scenario = load_scenario(c['scenario_id'], version=c.get('scenario_version', '1.0'))
        self.meta.update({k: v for k, v in scenario.items() if k != 'text'})
        self.out = Path(c['output']['directory']) / self.meta['run_id']
        log = c['logging']
        self.enabled = {name: log[name] for name in ('agent_states', 'events', 'model_states')}
        if c['model'] in ('covasim','fish'):
            self.enabled['contacts'] = log['contacts']
        if c['model']=='fish':
            self.enabled['raw_frames']=log['agent_states']
        self.writer = TrajectoryWriter(self.out, self.meta, batch_size=log['batch_size'], compression=log['compression'], enabled=self.enabled, checkpointing=live_snapshots)
        (self.out / 'resolved_config.yaml').write_text(yaml.safe_dump(c, sort_keys=False), encoding='utf-8')
        if scenario is not None:
            (self.out / 'scenario.md').write_bytes((Path(__file__).resolve().parents[2]/scenario['scenario_file']).read_bytes())
        self.started = datetime.now(timezone.utc).isoformat()
        self.completed = 0
        self.last_snapshot = -1
        self.closed = False
        try:
            if c['model'].startswith('schelling'):
                cls = ExtendedSchelling if c['model'] == 'schelling_extended' else Schelling
                self.model = cls(**c['parameters'], seed=c['seed'], event=lambda row: self.writer.record('events', row))
            elif c['model']=='fish':
                from simulations.fish.adapter import FishSimulation
                self.model=FishSimulation(c['parameters'],c['seed'],event=lambda row:self.writer.record('events',row),contact=lambda row:self.writer.record('contacts',row))
            else:
                self.model = RemoteCovasim(c, self.writer.record, self.out)
            self.snapshot()
        except Exception as exc:
            self.close('error', f'{type(exc).__name__}: {exc}')
            raise

    def snapshot(self):
        for state in self.model.states():
            self.writer.record('agent_states', state)
        if self.config['model']=='fish':
            self.writer.record('raw_frames',dict(event_type='native_raw_frame',frame_json=json.dumps(self.model.raw_frame(),allow_nan=False)))
        self.writer.record('model_states', self.model.summary())
        self.writer.save_checkpoint()
        self.last_snapshot = self.completed

    def advance(self):
        if self.closed:
            return
        self.writer.step = self.completed + 1
        try:
            self.model.step()
            self.completed += 1
            finished = not self.model.running or self.completed >= self.config['steps']
            if self.completed % self.config['sampling']['frequency'] == 0 or finished:
                self.snapshot()
            if finished:
                self.close((getattr(self.model, 'stop_reason', None) or 'stable') if self.config['model'].startswith('schelling') and not self.model.running else 'max_steps')
        except Exception as exc:
            self.close('error', f'{type(exc).__name__}: {exc}')
            raise

    def close(self, reason='interrupted', error=None):
        if self.closed:
            return
        self.closed = True
        checksums = {}
        try:
            # An interrupted UI run must still retain its last completed state.
            if reason == 'interrupted' and self.last_snapshot != self.completed:
                self.writer.step = self.completed
                self.snapshot()
            checksums = self.writer.close()
        except Exception as exc:
            reason = 'error'
            error = f'log finalization failed: {type(exc).__name__}: {exc}'
            raise
        finally:
            if self.config['model'] == 'covasim' and hasattr(self, 'model'):
                self.model.close()
            try:
                git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
                revision = git.stdout.strip() if git.returncode == 0 else None
                status = subprocess.run(['git', 'status', '--porcelain'], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
                dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
            except OSError:
                revision, dirty = None, None
            missing = [name for name, included in self.enabled.items() if not included]
            if self.config['sampling']['frequency'] > 1:
                missing.append('intermediate state snapshots between sampling steps')
            if reason == 'error':
                missing.append('run may be incomplete')
            source = 'User-provided collective_motion_lab fish-3.0; unmodified core' if self.meta['model_name']=='fish' else 'Study-specific heterogeneous local-relocation Schelling extension' if self.meta['model_name'] == 'schelling_extended' else 'Mesa 3.5.2 Schelling example' if self.meta['model_name'].startswith('schelling') else 'Native Covasim 2.0.0; uncalibrated hybrid demonstration'
            versions = {'mesa': mesa.__version__, 'numpy': numpy.__version__, 'pandas': pandas.__version__, 'pyarrow': pyarrow.__version__, 'pyyaml': yaml.__version__}
            engine_versions = getattr(getattr(self, 'model', None), 'engine_versions', {})
            if self.config['model'] == 'covasim':
                missing += ['unrealized transmission attempts are not exposed by native engine', 'within-day repeated testing of same person is not individually exposed', 'historical calibration and LTCF layer not present in demonstration']
            manifest = dict(self.meta, model_source=source, parameters=self.config['parameters'], requested_steps=self.config['steps'], sampling=self.config['sampling'], started_at=self.started, ended_at=datetime.now(timezone.utc).isoformat(), actual_steps=self.completed, status=reason, error=error, python=platform.python_version(), mesa=mesa.__version__, software_versions=versions, git_commit=revision, git_dirty=dirty, missing_data=missing, checksums_sha256=checksums)
            manifest.update(engine_versions=engine_versions, historical_reproduction=False)
            manifest.update(logging=self.config['logging'], scenario_integrity_verified=True,
                            recording_mode='full_observable' if all(self.enabled.values()) and self.config['sampling']['frequency'] == 1 else 'reduced')
            (self.out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            logging.getLogger('abms_lab').info('run %s finished: %s after %d steps', self.meta['run_id'], reason, self.completed)


def run(c):
    session = RunSession(c)
    try:
        while not session.closed:
            session.advance()
    finally:
        session.close()
    return session.out


def _parameter_target(config, path):
    """Resolve existing dotted YAML paths; integers index intervention lists."""
    if not isinstance(path, str) or not path:
        raise ValueError('batch parameter paths must be nonempty strings')
    parts = path.split('.')
    if parts[0] != 'parameters' and path != 'steps':
        parts.insert(0, 'parameters')
    node = config
    try:
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) and part.isdecimal() else node[part]
        key = int(parts[-1]) if isinstance(node, list) and parts[-1].isdecimal() else parts[-1]
        node[key]  # Reject accidental creation or misspellings.
        if isinstance(key, int) and key < 0:
            raise IndexError(key)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f'unknown batch parameter path: {path}') from exc
    return node, key, '.'.join(parts)


def batch(path):
    spec = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(spec, dict) or set(spec) not in ({'base_config', 'seeds', 'grid'}, {'base_config', 'master_seed', 'replicates', 'grid'}):
        raise ValueError('batch requires base_config, grid and either seeds or master_seed plus replicates')
    if not isinstance(spec['base_config'], str) or not isinstance(spec['grid'], dict) or any(not isinstance(v, list) or not v for v in spec['grid'].values()):
        raise ValueError('invalid batch base_config or grid')
    base = load(Path(path).parent / spec['base_config'])
    normalized = [_parameter_target(base, key)[2] for key in spec['grid']]
    if any(a == b or a.startswith(b+'.') or b.startswith(a+'.')
           for index, a in enumerate(normalized) for b in normalized[index+1:]):
        raise ValueError('overlapping batch parameter paths')
    seeds = spec.get('seeds')
    if seeds is None:
        if type(spec['master_seed']) is not int or spec['master_seed'] < 0 or type(spec['replicates']) is not int or not 1 <= spec['replicates'] <= 100000:
            raise ValueError('invalid master_seed or replicates')
        seeds = random.Random(spec['master_seed']).sample(range(2**32), spec['replicates'])
    if not isinstance(seeds, list) or not seeds or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds):
        raise ValueError('seeds must be a nonempty list of nonnegative integers')
    keys = list(spec['grid'])
    outcomes = []
    for values in itertools.product(*(spec['grid'][k] for k in keys)):
        for seed in seeds:
            c = copy.deepcopy(base)
            c['seed'] = seed
            for key, value in zip(keys, values):
                node, field, _ = _parameter_target(c, key)
                node[field] = copy.deepcopy(value)
            try:
                outcomes.append({'seed': seed, 'parameters': dict(zip(keys, values)), 'run': str(run(c)), 'error': None})
            except Exception as exc:
                outcomes.append({'seed': seed, 'parameters': dict(zip(keys, values)), 'error': str(exc)})
    output = Path(base['output']['directory'])
    output.mkdir(parents=True, exist_ok=True)
    report = output / ('batch_' + uuid.uuid4().hex + '.json')
    report.write_text(json.dumps(outcomes, indent=2), encoding='utf-8')
    return report
