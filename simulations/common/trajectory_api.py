"""The single entry point for trajectory writing, reading and trusted indicators.

Indicator callables run in this process and must have been reviewed. No Python
code here purports to sandbox untrusted code: use an external isolated runtime.
"""
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


# Explicit schemas prevent a first all-null or empty batch from changing types.
COMMON = {
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
D_STATE = {'opinion': (pa.float64(), 'Continuous opinion')}
D_EVENT = {
    'partner_id': (pa.int64(), 'Second agent in pair'),
    **{k: (pa.float64(), k.replace('_', ' ')) for k in ('opinion_before', 'partner_opinion_before', 'opinion_after', 'partner_opinion_after', 'difference', 'epsilon', 'mu', 'delta', 'partner_delta')},
    'accepted': (pa.bool_(), 'Whether strict confidence condition held'),
    'reason': (pa.string(), 'Reason for update or no update'),
}
S_MODEL = {k: (pa.int64(), k.replace('_', ' ')) for k in ('population', 'happy', 'same_neighbors', 'neighbors')}
D_MODEL = {'population': (pa.int64(), 'Population'), **{k: (pa.float64(), k.replace('_', ' ')) for k in ('mean_opinion', 'min_opinion', 'max_opinion')}}


def _definitions(model):
    additions = (S_FIELDS, S_EVENT, S_MODEL) if model == 'schelling' else (D_STATE, D_EVENT, D_MODEL)
    return {name: COMMON | fields for name, fields in zip(('agent_states', 'events', 'model_states'), additions)}


def _digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class TrajectoryWriter:
    def __init__(self, directory, metadata, batch_size=1024, compression='zstd', enabled=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.metadata = metadata
        self.batch_size, self.compression = batch_size, compression
        self.enabled = enabled or {'agent_states': True, 'events': True, 'model_states': True}
        self.definitions = _definitions(metadata['model_name'])
        self.schemas = {name: pa.schema([(key, value[0]) for key, value in fields.items()]) for name, fields in self.definitions.items()}
        self.buffers = {name: [] for name in self.definitions}
        self.writers = {}
        self.counts = dict.fromkeys(self.definitions, 0)
        self.event_index = 0
        self.step = 0

    def record(self, name, row):
        if name == 'events':
            self.event_index += 1
        if not self.enabled[name]:
            return
        common = {k: self.metadata[k] for k in ('run_id', 'model_name', 'model_version', 'seed')}
        common.update(step=self.step, event_index=self.event_index, timestamp_or_sim_time=self.step, agent_id=None, event_type=name)
        common.update(row)
        unknown = set(common) - set(self.schemas[name].names)
        if unknown:
            raise ValueError(f'Unknown {name} fields: {sorted(unknown)}')
        self.buffers[name].append(common)
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
            granularity = {'agent_states': 'agent per sampled step', 'events': 'attempted agent action or pair', 'model_states': 'one per sampled step'}[name]
            catalog[name] = {'granularity': granularity, 'fields': {key: {'type': str(typ), 'description': desc} for key, (typ, desc) in self.definitions[name].items()}}
        (self.directory / 'field_catalog.json').write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding='utf-8')
        return checksums


class Trajectory:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.catalog = json.loads((self.directory / 'field_catalog.json').read_text(encoding='utf-8'))

    def read(self, name, start=None, end=None, agent_id=None):
        if name not in self.catalog:
            raise ValueError(f'{name} was not recorded or does not exist')
        filters = []
        if start is not None:
            filters.append(('step', '>=', start))
        if end is not None:
            filters.append(('step', '<=', end))
        data = pq.read_table(self.directory / f'{name}.parquet', filters=filters or None).to_pandas()
        if agent_id is not None:
            mask = data.agent_id == agent_id
            if name == 'events' and 'partner_id' in data:
                mask |= data.partner_id == agent_id
            data = data[mask]
        return data.copy(deep=True)

    def export(self, destination):
        """Copy recorded Parquet tables and accompanying run metadata."""
        import shutil
        dest = Path(destination)
        dest.mkdir(parents=True, exist_ok=True)
        for name in self.catalog:
            shutil.copy2(self.directory / f'{name}.parquet', dest / f'{name}.parquet')
        for name in ('field_catalog.json', 'manifest.json', 'resolved_config.yaml'):
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
