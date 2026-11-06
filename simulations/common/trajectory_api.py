"""The single entry point for trajectory writing, reading and trusted indicators.

Indicator callables run in this process and must have been reviewed. No Python
code here purports to sandbox untrusted code: use an external isolated runtime.
"""
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def send_record(table, row):
    """Line-oriented transport for the isolated native-engine subprocess."""
    import sys
    sys.stdout.write('ABMS_RECORD:' + json.dumps({'table': table, 'row': row}, allow_nan=False) + '\n')
    sys.stdout.flush()


def receive_records(stream):
    """Ignore upstream banner text and decode only the explicit record protocol."""
    for line in stream:
        if line.startswith('ABMS_RECORD:'):
            message = json.loads(line[len('ABMS_RECORD:'):])
            yield message['table'], message['row']


# Explicit schemas prevent a first all-null or empty batch from changing types.
COMMON = {
    'scenario_id': (pa.string(), 'Fixed scenario identifier'),
    'scenario_version': (pa.string(), 'Fixed scenario text version'),
    'scenario_sha256': (pa.string(), 'SHA-256 of fixed scenario bytes'),
    'run_id': (pa.string(), 'Unique run identifier'),
    'model_name': (pa.string(), 'Model identifier'),
    'model_version': (pa.string(), 'Implementation version'),
    'seed': (pa.int64(), 'Random seed'),
    'step': (pa.int64(), 'Sampling step; initial state is zero'),
    'event_index': (pa.int64(), 'Cumulative attempted events in this run'),
    'timestamp_or_sim_time': (pa.int64(), 'Discrete sampling step, not wall time'),
    'agent_id': (pa.int64(), 'Actor ID; null for model states'),
    'event_type': (pa.string(), 'Record type'),
}
S_FIELDS = {
    'kind': (pa.int64(), 'Resident group, 0 or 1'),
    'x': (pa.int64(), 'Grid x coordinate'), 'y': (pa.int64(), 'Grid y coordinate'),
    'neighbors': (pa.int64(), 'Number of occupied neighbors'),
    'same_neighbors': (pa.int64(), 'Number of same-kind neighbors'),
    'other_neighbors': (pa.int64(), 'Number of other-kind neighbors'),
    'happy': (pa.bool_(), 'Happiness evaluated at snapshot'),
}
S_EVENT = {
    'kind': S_FIELDS['kind'],
    **{k: (pa.int64(), k.replace('_', ' ')) for k in ('x_before', 'y_before', 'x_after', 'y_after', 'neighbors', 'same_neighbors', 'other_neighbors', 'neighbors_after', 'same_neighbors_after', 'other_neighbors_after')},
    'happy_before': (pa.bool_(), 'Stored satisfaction used for this activation'),
    'happy_after': (pa.bool_(), 'Stored satisfaction after activation; recalculated only after the sweep'),
    'moved': (pa.bool_(), 'Whether the resident moved'),
    'reason': (pa.string(), 'Reason for movement or no movement'),
}
S_MODEL = {k: (pa.int64(), k.replace('_', ' ')) for k in ('population', 'happy', 'same_neighbors', 'neighbors')}
EXT_STATE = S_FIELDS | {'theta_i': (pa.float64(), 'Fixed individual preference from truncated normal initialization')}
EXT_EVENT = S_EVENT | {'theta_i': EXT_STATE['theta_i'], 'attempted': (pa.bool_(), 'Unsatisfied at actual activation; exhaustive local search attempted'),
                       'happy_before': (pa.bool_(), 'Satisfaction recomputed using current neighbors at activation'),
                       'happy_after': (pa.bool_(), 'Satisfaction immediately after own activation; final snapshot includes later neighbor moves'),
                       'candidate_count': (pa.int64(), 'Vacant local candidate cells'),
                       'feasible_count': (pa.int64(), 'Satisfactory candidates, otherwise strictly improving candidates'),
                       'similarity_before': (pa.float64(), 'Occupied same-kind neighbor proportion before activation'),
                       'similarity_after': (pa.float64(), 'Occupied same-kind neighbor proportion after activation')}
EXT_MODEL = S_MODEL | {'moves': (pa.int64(), 'Actual relocations in this completed sweep')}

C_FLAGS = ('susceptible', 'exposed', 'infectious', 'symptomatic', 'severe', 'critical',
           'tested', 'diagnosed', 'recovered', 'dead', 'known_contact', 'quarantined')
C_DAY = {'simulation_day': (pa.int64(), 'Covasim day; -1 is initialized pre-day-zero state')}
C_PERSON = C_DAY | {'uid': (pa.int64(), 'Covasim person UID')}
C_PERSON.update({key: (pa.float64(), key.replace('_', ' ')) for key in
                 ('age', 'sex', 'symp_prob', 'severe_prob', 'crit_prob', 'death_prob', 'rel_trans', 'rel_sus')})
C_PERSON.update({key: (pa.bool_(), 'Native Covasim ' + key) for key in C_FLAGS})
C_PERSON.update({key: (pa.float64(), 'Native Covasim day or duration; null when unset') for key in
                 tuple('date_' + flag for flag in C_FLAGS) + ('date_pos_test', 'date_end_quarantine',
                 'dur_exp2inf', 'dur_inf2sym', 'dur_sym2sev', 'dur_sev2crit', 'dur_disease')})
C_EVENT = C_DAY | {'partner_id': (pa.int64(), 'Infection source; null for seed/importation or status event'),
                      'layer': (pa.string(), 'Original Covasim contact layer'),
                      'state': (pa.string(), 'Changed native state'),
                      'before': (pa.bool_(), 'Previous boolean state'), 'after': (pa.bool_(), 'New boolean state')}
C_CONTACT = C_DAY | {'partner_id': (pa.int64(), 'Second endpoint of potential contact edge'),
                        'layer': (pa.string(), 'Original contact layer'), 'beta': (pa.float64(), 'Native edge weight, not realized transmission probability')}
C_MODEL = C_DAY | {key: (pa.int64(), 'Unscaled simulated count: ' + key) for key in ('population',) + C_FLAGS}
F_STATE={'role':(pa.string(),'fish or shark'),**{key:(pa.float64(),key) for key in ('x','y','heading','vx','vy')},
         'fright':(pa.int64(),'Native action episode: 0 ordinary, 1 direct, 2 social; same presentation as source'),
         'remaining':(pa.int64(),'Remaining fright steps after update'), 'target_id':(pa.int64(),'Shark target UID, -1 when absent')}
F_EVENT={'role':F_STATE['role'],**{key:(pa.float64(),key) for key in ('x_before','y_before','x_after','y_after','heading')},
         'decision_json':(pa.string(),'Lossless native individual decision fields and random draws')}
F_CONTACT={'partner_id':(pa.int64(),'Source neighbor UID'), 'source_episode':(pa.int64(),'Source fright episode at decision time')}
F_MODEL={'population':(pa.int64(),'Fish count'), 'predators':(pa.int64(),'Shark count'),'elapsed':(pa.float64(),'Native elapsed model time')}


def _definitions(model):
    if model=='fish':
        return {name:COMMON|fields for name,fields in (('agent_states',F_STATE),('events',F_EVENT),('contacts',F_CONTACT),
                 ('raw_frames',{'frame_json':(pa.string(),'Exact native fish-3.0 raw_frame JSON')}),('model_states',F_MODEL))}
    if model == 'covasim':
        return {name: COMMON | fields for name, fields in
                (('agent_states', C_PERSON), ('events', C_EVENT), ('model_states', C_MODEL), ('contacts', C_CONTACT))}
    if model == 'schelling_extended':
        return {name: COMMON | fields for name, fields in zip(('agent_states', 'events', 'model_states'), (EXT_STATE, EXT_EVENT, EXT_MODEL))}
    if model not in ('schelling', 'schelling_standard'):
        raise ValueError(f'Unknown model: {model}')
    additions = (S_FIELDS, S_EVENT, S_MODEL)
    return {name: COMMON | fields for name, fields in zip(('agent_states', 'events', 'model_states'), additions)}


def _digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class TrajectoryWriter:
    def __init__(self, directory, metadata, batch_size=1024, compression='zstd', enabled=None, checkpointing=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.metadata = metadata
        self.batch_size, self.compression = batch_size, compression
        self.definitions = _definitions(metadata['model_name'])
        self.enabled = enabled or {name: True for name in self.definitions}
        self.schemas = {name: pa.schema([(key, value[0]) for key, value in fields.items()]) for name, fields in self.definitions.items()}
        self.buffers = {name: [] for name in self.definitions}
        self.writers = {}
        self.counts = dict.fromkeys(self.definitions, 0)
        self.event_index = 0
        self.step = 0
        self.checkpointing = checkpointing
        # Commit model_states last: its appearance marks a complete frame.
        self.checkpoint_rows = {name: [] for name in ('agent_states', 'events', 'contacts', 'raw_frames', 'model_states') if name in self.definitions}
        if checkpointing:
            (self.directory / 'checkpoints').mkdir()
            self._write_catalog()
        (self.directory / 'run_metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')

    def _write_catalog(self):
        granularities = {'agent_states': 'agent per sampled step', 'events': 'observed model event', 'model_states': 'one per sampled step', 'contacts': 'native recorded interaction/contact edge', 'raw_frames':'lossless native frame per sampled step'}
        catalog = {name: {'granularity': granularities[name], 'fields': {key: {'type': str(typ), 'description': desc} for key, (typ, desc) in fields.items()}}
                   for name, fields in self.definitions.items() if self.enabled[name]}
        (self.directory / 'field_catalog.json').write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding='utf-8')

    def save_checkpoint(self):
        """Closed Parquet snapshots for live inspection; never interpolate or rerun."""
        if not self.checkpointing:
            return
        for name, rows in self.checkpoint_rows.items():
            if self.enabled[name]:
                destination = self.directory / 'checkpoints' / f'{name}_{self.step:06d}.parquet'
                temporary = destination.with_suffix('.tmp')
                pq.write_table(pa.Table.from_pylist(rows, schema=self.schemas[name]), temporary, compression=self.compression)
                temporary.replace(destination)
            rows.clear()

    def record(self, name, row):
        if name in ('native_parameters', 'native_parameters_final'):
            (self.directory / f'{name}.json').write_text(json.dumps(row, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            return
        if name == 'events':
            self.event_index += 1
        if not self.enabled[name]:
            return
        common = {k: self.metadata[k] for k in ('run_id', 'model_name', 'model_version', 'seed')}
        common.update({k: self.metadata.get(k) for k in ('scenario_id', 'scenario_version', 'scenario_sha256')})
        common.update(step=self.step, event_index=self.event_index, timestamp_or_sim_time=self.step, agent_id=None, event_type=name)
        common.update(row)
        unknown = set(common) - set(self.schemas[name].names)
        if unknown:
            raise ValueError(f'Unknown {name} fields: {sorted(unknown)}')
        self.buffers[name].append(common)
        if self.checkpointing and name in self.checkpoint_rows:
            self.checkpoint_rows[name].append(common)
        if len(self.buffers[name]) >= self.batch_size:
            self.flush(name)

    def flush(self, name):
        rows = self.buffers[name]
        if not rows:
            return
        if name not in self.writers:
            self.writers[name] = pq.ParquetWriter(self.directory / f'{name}.parquet', self.schemas[name], compression=self.compression)
        self.writers[name].write_table(pa.Table.from_pylist(rows, schema=self.schemas[name]))
        self.counts[name] += len(rows)
        rows.clear()

    def close(self):
        catalog, checksums = {}, {}
        for name in self.buffers:
            if not self.enabled[name]:
                continue
            self.flush(name)
            path = self.directory / f'{name}.parquet'
            if name in self.writers:
                self.writers[name].close()
            else:
                pq.write_table(pa.Table.from_pylist([], schema=self.schemas[name]), path, compression=self.compression)
            metadata = pq.read_metadata(path)
            if metadata.num_rows != self.counts[name] or not pq.read_schema(path).equals(self.schemas[name]):
                raise IOError(f'Parquet verification failed: {path}')
            checksums[path.name] = _digest(path)
            granularity = {'agent_states': 'agent per sampled step', 'events': 'observed model event', 'model_states': 'one per sampled step', 'contacts': 'native recorded interaction/contact edge', 'raw_frames':'lossless native frame per sampled step'}[name]
            catalog[name] = {'granularity': granularity, 'fields': {key: {'type': str(typ), 'description': desc} for key, (typ, desc) in self.definitions[name].items()}}
        (self.directory / 'field_catalog.json').write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding='utf-8')
        for name in ('native_parameters.json', 'native_parameters_final.json'):
            if (self.directory / name).exists():
                checksums[name] = _digest(self.directory / name)
        return checksums


class Trajectory:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.catalog = json.loads((self.directory / 'field_catalog.json').read_text(encoding='utf-8'))

    def configuration(self):
        import yaml
        return yaml.safe_load((self.directory / 'resolved_config.yaml').read_text(encoding='utf-8'))

    def metadata(self):
        path = self.directory / 'manifest.json'
        if not path.exists():
            path = self.directory / 'run_metadata.json'
        return json.loads(path.read_text(encoding='utf-8'))

    def source_fingerprints(self):
        paths = list(self.directory.glob('*.parquet')) if (self.directory / 'manifest.json').exists() else list((self.directory / 'checkpoints').glob('*.parquet'))
        return {str(path.relative_to(self.directory)): _digest(path) for path in sorted(paths)}

    def read(self, name, start=None, end=None, agent_id=None):
        if name not in self.catalog:
            raise ValueError(f'{name} was not recorded or does not exist')
        filters = []
        if start is not None:
            filters.append(('step', '>=', start))
        if end is not None:
            filters.append(('step', '<=', end))
        source = self.directory / f'{name}.parquet'
        if not (self.directory / 'manifest.json').exists() and (self.directory / 'checkpoints').exists():
            source = sorted((self.directory / 'checkpoints').glob(f'{name}_*.parquet'))
            if not source:
                raise ValueError(f'No completed checkpoint for {name}')
        data = pq.read_table(source, filters=filters or None).to_pandas()
        if agent_id is not None:
            mask = data.agent_id == agent_id
            if 'partner_id' in data:
                mask |= data.partner_id == agent_id
            data = data[mask]
        return data.copy(deep=True)

    def available_steps(self):
        return sorted(int(s) for s in self.read('model_states').step.unique())

    def read_snapshot(self, step):
        if step not in self.available_steps():
            raise ValueError(f'Step {step} was not recorded; select an actual sampled step')
        return self.read('agent_states', start=step, end=step)

    def read_frame(self,step):
        """Exact migrated native frame; never recomputed from a replay engine."""
        if step not in self.available_steps():
            raise ValueError(f'Step {step} was not recorded')
        rows=self.read('raw_frames',start=step,end=step)
        if len(rows)!=1:
            raise ValueError('Expected exactly one native raw frame')
        return json.loads(rows.iloc[0].frame_json)

    def export(self, destination):
        """Copy recorded Parquet tables and accompanying run metadata."""
        import shutil
        dest = Path(destination)
        dest.mkdir(parents=True, exist_ok=True)
        for name in self.catalog:
            shutil.copy2(self.directory / f'{name}.parquet', dest / f'{name}.parquet')
        for name in ('field_catalog.json', 'manifest.json', 'run_metadata.json', 'resolved_config.yaml', 'scenario.md', 'native_parameters.json', 'native_parameters_final.json'):
            source = self.directory / name
            if source.exists():
                shutil.copy2(source, dest / name)

    def compute(self, function, required, config=None):
        """Execute a reviewed callable on detached copies; not an untrusted-code sandbox."""
        for table, fields in required.items():
            if table not in self.catalog:
                raise ValueError(f'{table}: table was not recorded')
            missing = set(fields) - set(self.catalog.get(table, {}).get('fields', {}))
            if missing:
                raise ValueError(f'{table}: missing fields {sorted(missing)}')
        data = {name: self.read(name) for name in required}
        result = function(data, dict(config or {}))
        import pandas as pd
        if not isinstance(result, (pd.Series, pd.DataFrame)):
            raise TypeError('indicator must return a pandas Series or DataFrame')
        return result

    def compute_isolated(self, code_file, required, config=None, *, image='abms-indicator:1', timeout=30):
        """Run an untrusted indicator inside a separately provisioned Docker container.

        Docker must be explicitly installed and the image built beforehand. This
        fails closed if Docker is absent. Containers share the host kernel: for
        adversarial code use an independently hardened VM as an additional boundary.
        The input run and code are mounted read-only, networking is disabled, and
        no host credentials or writable host mounts are supplied.
        """
        import shutil
        import subprocess
        import tempfile
        import time
        import uuid

        for table, fields in required.items():
            if table not in self.catalog:
                raise ValueError(f'{table}: table was not recorded')
            missing = set(fields) - set(self.catalog.get(table, {}).get('fields', {}))
            if missing:
                raise ValueError(f'{table}: missing fields {sorted(missing)}')
        if not required or not 1 <= timeout <= 300:
            raise ValueError('provide required tables and a timeout between 1 and 300 seconds')
        docker = shutil.which('docker')
        if docker is None:
            raise RuntimeError('Docker is unavailable; untrusted indicator was not executed')
        name = 'abms-indicator-' + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix='abms_indicator_') as tmp:
            stage = Path(tmp)
            shutil.copyfile(code_file, stage / 'indicator.py')
            (stage / 'input.json').write_text(json.dumps({'tables': list(required), 'config': config or {}}), encoding='utf-8')
            (stage / 'harness.py').write_text(_ISOLATED_HARNESS, encoding='utf-8')
            command = [docker, 'run', '--rm', '--name', name, '--pull=never', '--network=none', '--read-only',
                       '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=32', '--memory=512m',
                       '--cpus=1', '--user=65534:65534', '--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=64m',
                       '--mount', f'type=bind,src={stage.resolve()},dst=/code,readonly',
                       '--mount', f'type=bind,src={self.directory.resolve()},dst=/data,readonly',
                       image, 'python', '-I', '/code/harness.py']
            log = stage / 'output.log'
            with log.open('wb') as output:
                process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + timeout
                try:
                    while process.poll() is None:
                        if time.monotonic() > deadline or log.stat().st_size > 4_000_000:
                            raise RuntimeError('isolated indicator exceeded time or output limit')
                        time.sleep(.1)
                finally:
                    if process.poll() is None:
                        subprocess.run([docker, 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
                        process.kill()
                        process.wait()
            if log.stat().st_size > 4_000_000:
                raise RuntimeError('isolated indicator exceeded output limit')
            content = log.read_text(encoding='utf-8', errors='replace')
            marker = '\nABMS_RESULT:'
            if process.returncode or marker not in content:
                raise RuntimeError(f'isolated indicator failed: {content[-2000:]}')
            result = json.loads(content.rsplit(marker, 1)[1])
            import pandas as pd
            from io import StringIO
            return pd.read_json(StringIO(result), orient='table')


_ISOLATED_HARNESS = '''
import importlib.util
import json
from pathlib import Path
import pandas as pd
request = json.loads(Path('/code/input.json').read_text(encoding='utf-8'))
data = {name: pd.read_parquet('/data/' + name + '.parquet').copy(deep=True) for name in request['tables']}
spec = importlib.util.spec_from_file_location('indicator', '/code/indicator.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.compute_indicator(data, request['config'])
if isinstance(result, pd.Series):
    result = result.to_frame()
if not isinstance(result, pd.DataFrame):
    raise TypeError('indicator must return a pandas Series or DataFrame')
print('\\nABMS_RESULT:' + json.dumps(result.to_json(orient='table')))
'''
