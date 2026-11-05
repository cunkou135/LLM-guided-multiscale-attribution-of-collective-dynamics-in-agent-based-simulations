import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from simulations.common.runner import batch, load, run, validate
from simulations.common.trajectory_api import Trajectory
from simulations.deffuant.model import Deffuant


@pytest.fixture
def config(tmp_path):
    c = load('configs/deffuant.yaml')
    c['output']['directory'] = str(tmp_path)
    c['steps'] = 3
    c['parameters'].update(population=12, interactions_per_step=17)
    c['logging']['batch_size'] = 7
    return c


def test_reproducibility_queries_and_indicators(config, tmp_path):
    a, b = run(config), run(config)
    ta, tb = Trajectory(a), Trajectory(b)
    for table in ('agent_states', 'events', 'model_states'):
        pd.testing.assert_frame_equal(ta.read(table).drop(columns='run_id'), tb.read(table).drop(columns='run_id'))
    assert len(ta.read('events')) == 51
    assert len(ta.read('agent_states')) == 48
    assert len(ta.read('agent_states', start=1, end=2, agent_id=1)) == 2
    assert len(ta.read('events', agent_id=1)) > 0
    assert 'opinion' in ta.catalog['agent_states']['fields']
    out = ta.compute(lambda d, c: d['agent_states'].groupby('step').opinion.mean(), {'agent_states': ['opinion', 'step']})
    assert len(out) == 4
    with pytest.raises(ValueError, match='missing'):
        ta.compute(lambda d, c: None, {'agent_states': ['absent']})
    with pytest.raises(TypeError, match='Series or DataFrame'):
        ta.compute(lambda d, c: None, {'agent_states': ['opinion']})
    def mutate(data, config):
        data['agent_states']['opinion'] = -999
        return data['agent_states'][['opinion']]
    ta.compute(mutate, {'agent_states': ['opinion']})
    assert ta.read('agent_states').opinion.min() >= 0
    ta.export(tmp_path / 'exported')
    assert (tmp_path / 'exported' / 'events.parquet').exists()
    assert (tmp_path / 'exported' / 'manifest.json').exists()
    manifest = json.loads((a / 'manifest.json').read_text())
    assert manifest['actual_steps'] == 3 and manifest['seed'] == config['seed']
    assert len(manifest['checksums_sha256']) == 3
    assert yaml.safe_load((a / 'resolved_config.yaml').read_text()) == config


def test_sampled_and_disabled(config):
    config['steps'] = 5
    config['sampling']['frequency'] = 3
    config['logging']['events'] = False
    output = run(config)
    t = Trajectory(output)
    assert sorted(t.read('agent_states').step.unique()) == [0, 3, 5]
    assert not (output / 'events.parquet').exists()
    assert 'events' in json.loads((output / 'manifest.json').read_text())['missing_data']


def test_empty_population_has_schema(tmp_path):
    c = load('configs/schelling.yaml')
    c['output']['directory'] = str(tmp_path)
    c['parameters']['density'] = 0
    t = Trajectory(run(c))
    assert t.read('agent_states').empty and t.read('events').empty
    assert 'agent_id' in t.read('events').columns


@pytest.mark.parametrize('path,value', [(['steps'], 0), (['seed'], -1), (['parameters', 'mu'], .6), (['parameters', 'epsilon'], float('nan')), (['parameters', 'initial_distribution'], 'bimodal'), (['logging', 'events'], 1), (['sampling', 'frequency'], 0)])
def test_validation_rejects_invalid(config, path, value):
    obj = config
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value
    with pytest.raises(ValueError):
        validate(config)


def test_batch_continues_after_invalid_case(config, tmp_path):
    base = tmp_path / 'base.yaml'
    base.write_text(yaml.safe_dump(config), encoding='utf-8')
    specification = tmp_path / 'batch.yaml'
    specification.write_text(yaml.safe_dump({'base_config': 'base.yaml', 'seeds': [1, 2], 'grid': {'mu': [.2, .9]}}), encoding='utf-8')
    outcomes = json.loads(batch(specification).read_text())
    assert len(outcomes) == 4
    assert sum(item['error'] is None for item in outcomes) == 2
    assert all(Path(item['run']).exists() for item in outcomes if item['error'] is None)


def test_logging_does_not_consume_model_randomness(config):
    t = Trajectory(run(config))
    model = Deffuant(**config['parameters'], seed=config['seed'])
    for _ in range(config['steps']):
        model.step()
    actual = t.read('agent_states', start=config['steps']).sort_values('agent_id')
    assert actual.opinion.tolist() == [a.opinion for a in model.agents]


def test_different_seed_changes_trajectory(config):
    first = Trajectory(run(config)).read('agent_states')
    config['seed'] += 1
    second = Trajectory(run(config)).read('agent_states')
    assert first.opinion.tolist() != second.opinion.tolist()


def test_failed_run_retains_manifest(tmp_path):
    c = load('configs/schelling.yaml')
    c['output']['directory'] = str(tmp_path)
    c['parameters'].update(width=4, height=4, density=1, minority_pc=.5, homophily=1)
    with pytest.raises(Exception):
        run(c)
    manifests = list(tmp_path.glob('*/manifest.json'))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert manifest['status'] == 'error' and manifest['error']


def test_isolation_fails_closed_without_docker(config, tmp_path, monkeypatch):
    import shutil
    t = Trajectory(run(config))
    code = tmp_path / 'indicator.py'
    code.write_text('raise RuntimeError("must not run on host")', encoding='utf-8')
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    with pytest.raises(RuntimeError, match='not executed'):
        t.compute_isolated(code, {'agent_states': ['opinion']})
    with pytest.raises(ValueError, match='not recorded'):
        t.compute_isolated(code, {'../other': []})


def test_master_seed_batch_is_repeatable(config, tmp_path):
    base = tmp_path / 'base.yaml'
    base.write_text(yaml.safe_dump(config), encoding='utf-8')
    spec = tmp_path / 'batch.yaml'
    spec.write_text(yaml.safe_dump({'base_config': 'base.yaml', 'master_seed': 100, 'replicates': 2, 'grid': {'mu': [0, .5]}}), encoding='utf-8')
    first, second = json.loads(batch(spec).read_text()), json.loads(batch(spec).read_text())
    assert [r['seed'] for r in first] == [r['seed'] for r in second]
    assert all(row['error'] is None for row in first + second)
