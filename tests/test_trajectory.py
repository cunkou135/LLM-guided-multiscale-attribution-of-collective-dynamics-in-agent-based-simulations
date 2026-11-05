import json
from pathlib import Path
import pandas as pd
import pytest
import yaml
from simulations.common.runner import load, run, batch, validate
from simulations.common.trajectory_api import Trajectory
from examples.indicators import covasim_infectious_fraction


@pytest.fixture
def config(tmp_path):
    c = load('configs/covasim.yaml')
    c['steps'] = 3
    c['parameters'].update(pop_size=30, pop_infected=3)
    c['output']['directory'] = str(tmp_path)
    return c


def test_repeatability_logs_and_indicator(config, tmp_path):
    a, b = run(config), run(config)
    ta, tb = Trajectory(a), Trajectory(b)
    for name in ('agent_states', 'events', 'model_states', 'contacts'):
        pd.testing.assert_frame_equal(ta.read(name).drop(columns='run_id'), tb.read(name).drop(columns='run_id'))
    assert len(ta.read('agent_states')) == 120
    assert len(ta.read('agent_states', start=1, end=2, agent_id=0)) == 2
    assert set(ta.read('contacts').layer) == {'h', 's', 'w', 'c'}
    assert len(ta.read('events').query("event_type == 'infection'")) >= 3
    assert len(ta.compute(covasim_infectious_fraction, {'agent_states': ['step', 'infectious']})) == 4
    with pytest.raises(ValueError, match='missing'):
        ta.compute(lambda d, c: None, {'agent_states': ['absent']})
    ta.export(tmp_path / 'exported')
    assert Trajectory(tmp_path / 'exported').read('contacts').equals(ta.read('contacts'))
    meta = json.loads((a / 'manifest.json').read_text())
    assert meta['actual_steps'] == 3 and meta['status'] == 'max_steps'
    assert meta['engine_versions']['covasim'] == '2.0.0'
    assert meta['historical_reproduction'] is False
    assert len(meta['checksums_sha256']) == 4


def test_low_resource_and_final_snapshot(config):
    config['steps'] = 5
    config['sampling']['frequency'] = 3
    config['logging'].update(events=False, contacts=False)
    out = run(config)
    t = Trajectory(out)
    assert sorted(t.read('agent_states').step.unique()) == [0, 3, 5]
    assert 'contacts' in json.loads((out / 'manifest.json').read_text())['missing_data']
    with pytest.raises(ValueError):
        t.read('events')


def test_independent_seed_changes_initial_population(config):
    config['steps'] = 2
    a = Trajectory(run(config)).read('agent_states', end=0)
    config['seed'] += 1
    b = Trajectory(run(config)).read('agent_states', end=0)
    assert a.age.tolist() != b.age.tolist()


def test_covasim_native_zero_duration_rejected(config):
    config['steps'] = 1
    with pytest.raises(ValueError, match='steps >= 2'):
        validate(config)


def test_native_engine_failure_preserves_error_and_log(config):
    config['parameters']['interventions'] = [{'type': 'test_prob', 'unknown_parameter': 1}]
    with pytest.raises(RuntimeError, match='engine.log'):
        run(config)
    directories = list(Path(config['output']['directory']).iterdir())
    assert len(directories) == 1
    manifest = json.loads((directories[0] / 'manifest.json').read_text())
    assert manifest['status'] == 'error' and manifest['actual_steps'] == 0
    assert 'TypeError' in (directories[0] / 'engine.log').read_text(encoding='utf-8')


@pytest.mark.parametrize('field,value', [('beta', float('nan')), ('pop_size', 0), ('pop_infected', -1), ('rescale', True)])
def test_invalid_parameters(config, field, value):
    config['parameters'][field] = value
    with pytest.raises(ValueError):
        validate(config)


def test_batch_preserves_successes_after_invalid_combination(tmp_path):
    c = load('configs/schelling.yaml')
    c['steps'] = 1
    c['output']['directory'] = str(tmp_path / 'out')
    (tmp_path / 'base.yaml').write_text(yaml.safe_dump(c))
    spec = tmp_path / 'batch.yaml'
    spec.write_text(yaml.safe_dump(dict(base_config='base.yaml', master_seed=11, replicates=2, grid={'homophily': [.4, 2.]})))
    rows = json.loads(batch(spec).read_text())
    assert len(rows) == 4 and sum(r['error'] is None for r in rows) == 2
    assert all(Path(r['run']).exists() for r in rows if r['error'] is None)


def test_empty_schelling_and_failed_run(tmp_path):
    c = load('configs/schelling.yaml')
    c['output']['directory'] = str(tmp_path)
    c['parameters']['density'] = 0
    assert Trajectory(run(c)).read('events').empty
    c['parameters'].update(width=4, height=4, density=1, homophily=1)
    with pytest.raises(ValueError):
        run(c)
    assert any(json.loads(p.read_text())['status'] == 'error' for p in tmp_path.glob('*/manifest.json'))


def test_untrusted_code_not_run_without_docker(tmp_path, monkeypatch):
    import shutil
    c = load('configs/schelling.yaml')
    c['output']['directory'] = str(tmp_path)
    c['steps'] = 1
    t = Trajectory(run(c))
    monkeypatch.setattr(shutil, 'which', lambda _: None)
    with pytest.raises(RuntimeError, match='not executed'):
        t.compute_isolated(tmp_path / 'untrusted.py', {'agent_states': ['happy']})
