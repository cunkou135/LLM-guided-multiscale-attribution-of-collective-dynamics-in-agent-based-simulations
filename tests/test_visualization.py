import json
import pandas as pd
import pytest

from simulations.common.runner import load, run
from simulations.common.trajectory_api import Trajectory
from visualization.app import VisualRun


@pytest.mark.parametrize('name', ['schelling', 'deffuant'])
def test_visual_and_headless_use_same_core(tmp_path, name):
    config = load(f'configs/{name}.yaml')
    config['steps'] = 3
    config['output']['directory'] = str(tmp_path)
    p = config['parameters']
    primary, secondary = (p['homophily'], p['density']) if name == 'schelling' else (p['epsilon'], p['mu'])
    visual = VisualRun(config, primary, secondary)
    while visual.running:
        visual.step()
    direct = run(config)
    a, b = Trajectory(visual.session.out), Trajectory(direct)
    for table in ('agent_states', 'events', 'model_states'):
        pd.testing.assert_frame_equal(a.read(table).drop(columns='run_id'), b.read(table).drop(columns='run_id'))


def test_visual_interrupted_run_saves_final_state(tmp_path):
    config = load('configs/deffuant.yaml')
    config['output']['directory'] = str(tmp_path)
    config['sampling']['frequency'] = 5
    v = VisualRun(config, .2, .5)
    v.step()
    v.close()
    output = v.session.out
    assert json.loads((output / 'manifest.json').read_text())['status'] == 'interrupted'
    assert set(Trajectory(output).read('agent_states').step) == {0, 1}
