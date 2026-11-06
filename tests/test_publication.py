import json

import pandas as pd
from PIL import Image
import pytest
import yaml

from simulations.common.runner import RunSession, batch, load, run
from simulations.common.trajectory_api import Trajectory
from visualization.figures import export_publication, figure_config, publication_figure, interactive_grid, intervention_schedule, interactive_covasim


def test_intervention_dates_are_mapped_to_recorded_steps():
    c=load('configs/covasim.yaml')
    c['parameters']['interventions'] = [
        {'type':'test_prob','start_day':'2020-02-16'},
        {'type':'change_beta','days':[5,10],'changes':[.8,.6]}]
    schedule=intervention_schedule(c)
    assert [row['recorded_step'] for row in schedule] == [21,6,11]


@pytest.mark.parametrize('name', ['schelling', 'covasim'])
def test_publication_matches_saved_data_and_is_repeatable(tmp_path, name):
    c = load(f'configs/{name}.yaml')
    c['steps'] = 3
    c['output']['directory'] = str(tmp_path / 'runs')
    if name == 'schelling':
        c['parameters'].update(width=12, height=12, relocation_radius=3)
    else:
        c['parameters'].update(pop_size=40, pop_infected=3)
    t = Trajectory(run(c))
    before = t.source_fingerprints()
    settings = figure_config()
    settings.update(width_inches=4., font_size=7)
    path = tmp_path / 'figures.yaml'
    path.write_text(yaml.safe_dump(settings))
    output = export_publication(t.directory, tmp_path / 'figures', path)
    data = json.loads((output / 'figure_data.json').read_text())
    manifest = json.loads((output / 'figure_manifest.json').read_text())
    for dpi in (300, 600):
        with Image.open(output / f'publication_{dpi}dpi.png') as image:
            assert image.size == (4*dpi, 3*dpi)
            assert abs(image.info['dpi'][0]-dpi) < .1
    svg = (output / 'publication.svg').read_bytes()
    assert b'<text' in svg
    if name == 'schelling':
        assert data['snapshot_steps'] == [0, 2, 3]
        assert data['curves'][-1]['move_count'] == t.read('events', start=3).moved.sum()
        frame = interactive_grid(t, 3)
        assert frame.layout.xaxis.range == (-.5, 11.5)
    else:
        raw = t.read('events').query("event_type == 'infection'")
        assert sum(data['layer_counts'].values()) == len(raw)
        assert set(row['event_index'] for row in data['network_edges']) <= set(raw.event_index)
        assert sum(sum(row[k] for k in ('susceptible','exposed','recovered','dead')) for row in data['age_counts']) == 40
        network = interactive_covasim(t, 0, settings)[1]
        assert not network.layout.annotations  # Empty initial graph cannot retain arrows from a later frame.
        assert len(network.data) == 1  # Exactly the recorded seed node; no transmission traces.
    assert manifest['source_fingerprints'] == before
    assert manifest['scenario_version'] == '2.0'
    export_publication(t.directory, output, path)
    assert (output / 'publication.svg').read_bytes() == svg
    assert t.source_fingerprints() == before
    with pytest.raises(ValueError, match='actually recorded'):
        publication_figure(t, settings, 300)
    settings['aspect'] = '16:9'
    fig, _ = publication_figure(t, settings)
    assert fig.get_size_inches()[1] == 2.25


def test_live_checkpoints_reconstruct_final_trajectory_without_random_draws(tmp_path):
    c = load('configs/schelling.yaml')
    c['parameters'].update(width=12, height=12, relocation_radius=3)
    c['output']['directory'] = str(tmp_path)
    c['steps'] = 3
    c['sampling']['frequency'] = 2
    session = RunSession(c, live_snapshots=True)
    t = Trajectory(session.out)
    assert t.available_steps() == [0]
    session.advance()
    assert t.available_steps() == [0]
    session.advance()
    state = session.model.random.getstate()
    snapshot = t.read_snapshot(2)
    events = t.read('events')
    assert set(events.step) == {1, 2}
    assert snapshot.theta_i.notna().all()
    interactive_grid(t, 2)
    assert session.model.random.getstate() == state
    with pytest.raises(ValueError, match='not recorded'):
        t.read_snapshot(1)
    session.close()
    pd.testing.assert_frame_equal(snapshot.reset_index(drop=True), t.read_snapshot(2).reset_index(drop=True))
    assert t.metadata()['status'] == 'interrupted'


def test_nested_native_intervention_batch_is_resolved_and_recorded(tmp_path):
    c = load('configs/covasim.yaml')
    c['steps'] = 2
    c['parameters'].update(pop_size=25, pop_infected=2)
    c['output']['directory'] = str(tmp_path / 'runs')
    (tmp_path / 'base.yaml').write_text(yaml.safe_dump(c))
    spec = dict(base_config='base.yaml', seeds=[8], grid={
        'interventions.0.symp_prob': [.2],
        'parameters.interventions.1.trace_probs.h': [.8]})
    file = tmp_path / 'batch.yaml'
    file.write_text(yaml.safe_dump(spec))
    results = json.loads(batch(file).read_text())
    assert len(results) == 1 and results[0]['error'] is None
    config = Trajectory(results[0]['run']).configuration()
    assert config['parameters']['interventions'][0]['symp_prob'] == .2
    assert config['parameters']['interventions'][1]['trace_probs']['h'] == .8
    spec['grid'] = {'interventions.99.symp_prob': [.1]}
    file.write_text(yaml.safe_dump(spec))
    with pytest.raises(ValueError, match='unknown batch parameter'):
        batch(file)
