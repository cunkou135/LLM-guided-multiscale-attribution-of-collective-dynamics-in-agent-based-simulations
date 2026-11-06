import copy
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from simulations.common.runner import RunSession,load,run
from simulations.common.trajectory_api import Trajectory
from simulations.fish.adapter import FishSimulation
from visualization.fish import fish_packet


@pytest.mark.parametrize('case',json.loads(Path('experiments/validation/fish_behavior_baseline.json').read_text())['cases'])
def test_migrated_raw_frames_match_user_source_exactly(case):
    config=load('configs/fish.yaml')
    parameters=copy.deepcopy(config['parameters'])
    parameters['population']['count']=case['count']
    parameters['fish']['N_p']=case['sharks']
    model=FishSimulation(parameters,case['seed'])
    for step,expected in enumerate(case['sha256']):
        actual=hashlib.sha256(json.dumps(model.raw_frame(),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        assert actual==expected
        if step<case['steps']:
            model.step()


def test_fish_live_logs_replay_and_headless_are_identical(tmp_path):
    c=load('configs/fish.yaml')
    c['parameters']['population']['count']=40
    c['steps']=4;c['output']['directory']=str(tmp_path)
    session=RunSession(c,live_snapshots=True)
    t=Trajectory(session.out)
    assert len(fish_packet(t,0)['agents'])==40
    session.advance()
    frame=t.read_frame(1)
    assert frame==session.model.raw_frame()
    assert len(t.read_snapshot(1))==45
    while not session.closed:
        session.advance()
    headless=Trajectory(run(c))
    for name in t.catalog:
        pd.testing.assert_frame_equal(t.read(name).drop(columns='run_id'),headless.read(name).drop(columns='run_id'))
    before=t.source_fingerprints()
    assert fish_packet(t,1)['step']==1
    assert t.source_fingerprints()==before
    assert (session.out/'scenario.md').read_bytes()==Path('scenarios/fish.md').read_bytes()
    assert t.metadata()['status']=='max_steps'


def test_migrated_engine_bytes_are_preserved():
    reference=json.loads(Path('experiments/validation/fish_behavior_baseline.json').read_text())
    assert hashlib.sha256(Path('simulations/fish/engine.py').read_bytes()).hexdigest()==reference['source_engine_sha256']
