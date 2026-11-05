"""Connect to Covasim 2.0.0 without replacing any transmission decisions.

This module has no Mesa import and can run in a separate Python environment.
All serialization and trajectory access remain in trajectory_api.py.
"""
import copy


def build_sim(config):
    import covasim as cv
    if cv.__version__ != '2.0.0':
        raise RuntimeError(f'Expected Covasim 2.0.0, found {cv.__version__}')
    parameters = copy.deepcopy(config['parameters'])
    interventions = []
    factories = {'test_prob': cv.test_prob, 'contact_tracing': cv.contact_tracing,
                 'change_beta': cv.change_beta, 'clip_edges': cv.clip_edges}
    for specification in parameters.pop('interventions'):
        kind = specification.pop('type')
        if kind not in factories:
            raise ValueError(f'Unsupported intervention: {kind}')
        interventions.append(factories[kind](**specification))
    # step=0 is before Covasim day 0; each subsequent platform step is one day.
    parameters.update(n_days=config['steps'] - 1, rand_seed=config['seed'], verbose=0)
    return cv.Sim(parameters, interventions=interventions)


class CovasimAdapter:
    def __init__(self, config):
        self.sim = build_sim(config)
        self.sim.initialize()
        self.day = -1
        self.running = True
        self._infection_cursor = 0
        self._before = self._state_copy()

    def _state_copy(self):
        p = self.sim.people
        return {name: p[name].copy() for name in list(p.meta.states) + ['date_tested']}

    def step(self):
        self._before = self._state_copy()
        self.day = self.sim.t
        self.sim.step()
        self.running = not self.sim.complete

    def states(self):
        import numpy as np
        p = self.sim.people
        for i, uid in enumerate(p.uid):
            row = {'agent_id': int(uid), 'event_type': 'state', 'simulation_day': self.day}
            for key in p.meta.all_states:
                value = p[key][i]
                row[key] = None if isinstance(value, (float, np.floating)) and not np.isfinite(value) else value.item() if hasattr(value, 'item') else value
            yield row

    def events(self):
        import numpy as np
        p = self.sim.people
        for event in p.infection_log[self._infection_cursor:]:
            yield dict(agent_id=int(event['target']), partner_id=int(event['source']) if event['source'] is not None else None,
                       event_type='infection', simulation_day=int(event['date']), layer=event['layer'], state=None,
                       before=None, after=None)
        self._infection_cursor = len(p.infection_log)
        if self.day < 0:
            return
        for key in p.meta.states:
            for i in np.flatnonzero(p[key] != self._before[key]):
                yield dict(agent_id=int(p.uid[i]), partner_id=None, event_type='state_transition',
                           simulation_day=self.day, layer=None, state=key,
                           before=bool(self._before[key][i]), after=bool(p[key][i]))
        # tested is an 'ever tested' flag, so detect repeats via last test date.
        for i in np.flatnonzero((p.date_tested == self.day) & (p.date_tested != self._before['date_tested'])):
            yield dict(agent_id=int(p.uid[i]), partner_id=None, event_type='test', simulation_day=self.day,
                       layer=None, state='date_tested', before=None, after=None)

    def contacts(self):
        for layer, edges in self.sim.people.contacts.items():
            for a, b, beta in zip(edges['p1'], edges['p2'], edges['beta']):
                yield dict(agent_id=int(a), partner_id=int(b), event_type='contact_edge',
                           simulation_day=self.day, layer=layer, beta=float(beta))

    def summary(self):
        p = self.sim.people
        return dict(simulation_day=self.day, population=len(p),
                    **{name: int(p[name].sum()) for name in p.meta.states})


class RemoteCovasim:
    """Stream native observations to a parent-owned trajectory writer."""
    def __init__(self, config, sink, directory):
        import subprocess
        import json
        import os
        from pathlib import Path
        self.sink = sink
        self.contact_counts = {}
        self._log = (Path(directory) / 'engine.log').open('w', encoding='utf-8')
        executable = Path(config['engine']['python']).resolve()
        self.process = subprocess.Popen([str(executable), '-u', '-m', 'simulations.covasim.adapter'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                                        text=True, encoding='utf-8', env=dict(os.environ, PYTHONIOENCODING='utf-8'), cwd=Path(__file__).resolve().parents[2])
        try:
            self.process.stdin.write(json.dumps(config) + '\n')
            self.process.stdin.flush()
            list(self._receive())
        except BaseException:
            self.close()
            raise

    def _receive(self):
        from simulations.common.trajectory_api import receive_records
        for table, row in receive_records(self.process.stdout):
            if table == 'ready':
                self._summary = row['summary']
                self.running = row['running']
                self.engine_versions = row['versions']
                return
            if table == 'agent_states':
                yield row
            else:
                if table == 'contacts':
                    self.contact_counts[row['layer']] = self.contact_counts.get(row['layer'], 0) + 1
                self.sink(table, row)
        raise RuntimeError('Covasim worker exited before completing command; inspect engine.log')

    def _command(self, command):
        self.process.stdin.write(command + '\n')
        self.process.stdin.flush()

    def step(self):
        self._command('step')
        list(self._receive())

    def states(self):
        self.contact_counts = {}
        self._command('snapshot')
        yield from self._receive()

    def summary(self):
        return self._summary

    def close(self):
        import subprocess
        try:
            if self.process.poll() is None:
                self._command('close')
                self.process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait()
        finally:
            for stream in (self.process.stdin, self.process.stdout):
                try:
                    stream.close()
                except OSError:
                    pass  # A worker failure can leave a broken buffered stdin.
            self._log.close()


def worker():
    """Native engine process; exchange records through the unified API transport."""
    import sys
    import json
    import platform
    from importlib.metadata import version
    import covasim as cv
    import numpy as np
    from simulations.common.trajectory_api import send_record
    config = json.loads(sys.stdin.readline())
    model = CovasimAdapter(config)
    send_record('native_parameters', model.sim.to_json(keys='parameters'))
    for row in model.events():
        send_record('events', row)
    versions = dict(python=platform.python_version(), covasim=cv.__version__, numpy=np.__version__)
    versions.update({name: version(name) for name in ('sciris', 'numba', 'scipy', 'pandas', 'pyarrow', 'matplotlib', 'PyYAML')})
    send_record('ready', dict(summary=model.summary(), running=model.running, versions=versions))
    for command in sys.stdin:
        if command.strip() == 'close':
            break
        if command.strip() == 'step':
            model.step()
            for row in model.events():
                send_record('events', row)
            if not model.running:
                send_record('native_parameters_final', model.sim.to_json(keys='parameters'))
        elif command.strip() == 'snapshot':
            if config['logging']['agent_states']:
                for row in model.states():
                    send_record('agent_states', row)
            if config['logging']['contacts']:
                for row in model.contacts():
                    send_record('contacts', row)
        else:
            raise ValueError('Unknown engine command')
        send_record('ready', dict(summary=model.summary(), running=model.running, versions=versions))


if __name__ == '__main__':
    worker()
