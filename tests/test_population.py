import copy

import pandas as pd
import pytest

from simulations.common.runner import RunSession, load, run
from simulations.common.trajectory_api import Trajectory
from visualization.population import disease_state, population_frame, population_layout, save_browser_capture


def test_native_people_contacts_and_live_display_do_not_change_dynamics(tmp_path):
    config=load('configs/covasim.yaml')
    config['parameters'].update(pop_size=50,pop_infected=5)
    config['steps']=4
    config['output']['directory']=str(tmp_path)
    live=RunSession(config,live_snapshots=True)
    t=Trajectory(live.out)
    initial=population_layout(str(t.directory.resolve()))
    frames=[]
    while not live.closed:
        frame=population_frame(t,live.completed,selected_uid=0)
        frames.append(frame)
        assert {node['id'] for node in frame['nodes']} == set(range(50))
        assert all(a in range(50) and b in range(50) and layer in 'hswc' for a,b,layer in frame['contacts'])
        assert population_layout(str(t.directory.resolve())) == initial
        raw=t.read_snapshot(live.completed).set_index('agent_id')
        for node in frame['nodes']:
            assert node['state'] == disease_state(raw.loc[node['id']])
            assert node['diagnosed'] == raw.loc[node['id']].diagnosed
        events=t.read('events',start=live.completed,end=live.completed)
        assert {event['event_index'] for event in frame['infections']} == set(events.loc[events.event_type=='infection','event_index'])
        live.advance()
    direct=Trajectory(run(config))
    for table in t.catalog:
        pd.testing.assert_frame_equal(t.read(table).drop(columns='run_id'),direct.read(table).drop(columns='run_id'))
    assert [f['step'] for f in frames] == [0,1,2,3]
    with pytest.raises(ValueError,match='Capture run'):
        save_browser_capture(t,{'run_id':'wrong'})


def test_disease_color_priority_preserves_overlapping_native_flags():
    row={name:False for name in ('susceptible','exposed','infectious','recovered','dead')}
    row.update(exposed=True,infectious=True)
    assert disease_state(row)=='infectious'
    row.update(recovered=True)
    assert disease_state(row)=='recovered'
    row.update(dead=True)
    assert disease_state(row)=='dead'
