"""Platform adapter around the byte-preserved, user-provided fish engine."""
import copy
import json
import math
from pathlib import Path

import numpy as np
import yaml

from simulations.fish.engine import FishModel


def controls():
    return yaml.safe_load((Path(__file__).resolve().parents[2]/'configs/fish_controls.yaml').read_text(encoding='utf-8'))


def validate_parameters(parameters):
    specs=controls()
    if set(parameters)!={'simulation','population','predator','fish'}:
        raise ValueError('Invalid fish parameter groups')
    values={f'{group}.{key}':value for group,items in parameters.items() for key,value in items.items()}
    if set(values)!=set(specs):
        raise ValueError('Fish parameters must match the migrated native controls')
    for path,value in values.items():
        spec=specs[path]
        if spec['type'] in ('int','float'):
            if type(value) not in (int,float) or not math.isfinite(value) or not spec['min']<=value<=spec['max'] or (spec['type']=='int' and type(value) is not int):
                raise ValueError(f'Invalid fish parameter: {path}')
        elif spec['type']=='select' and value not in spec['options']:
            raise ValueError(f'Invalid fish selection: {path}')
    f=parameters['fish']
    if not f['r_r']<f['r_a']<f['R_s']:
        raise ValueError('Fish radii must satisfy r_r < r_a < R_s')


class FishSimulation:
    def __init__(self,parameters,seed,event=None,contact=None):
        settings=copy.deepcopy(parameters)
        settings['simulation']['seed']=seed
        self.core=FishModel(settings)
        self.running=True
        self.event=event or (lambda row:None)
        self.contact=contact or (lambda row:None)
        self.engine_versions={'protocol':self.core.protocol_version,'source':'user-provided collective_motion_lab'}

    def step(self):
        self.core.step()
        model=self.core
        for index,agent in enumerate(model.flock):
            data={key:values[index] for key,values in model.decisions.items()}
            self.event(dict(agent_id=agent.unique_id,event_type='movement',role='fish',
                            x_before=model.last_input['positions'][index][0],y_before=model.last_input['positions'][index][1],
                            x_after=float(agent.position[0]),y_after=float(agent.position[1]),
                            heading=float(agent.heading),decision_json=json.dumps(data,allow_nan=False)))
        for index,agent in enumerate(model.predators):
            data={key:values[index] for key,values in model.shark_decisions.items()}
            self.event(dict(agent_id=agent.unique_id,event_type='movement',role='shark',
                            x_before=model.last_input['shark_positions'][index][0],y_before=model.last_input['shark_positions'][index][1],
                            x_after=float(agent.position[0]),y_after=float(agent.position[1]),
                            heading=float(agent.heading),decision_json=json.dumps(data,allow_nan=False)))
        for recipient,source,episode in model.contacts:
            self.contact(dict(agent_id=model.flock[recipient].unique_id,partner_id=model.flock[source].unique_id,
                              event_type='alarm_contact',source_episode=episode))

    def states(self):
        model=self.core
        for index,agent in enumerate(model.flock):
            yield dict(agent_id=agent.unique_id,role='fish',x=float(agent.position[0]),y=float(agent.position[1]),
                       heading=float(agent.heading),vx=float(model.velocity[index,0]),vy=float(model.velocity[index,1]),
                       fright=int(model.decisions['d'][index])+2*int(model.decisions['s'][index]),
                       remaining=int(model.remaining[index]),target_id=None)
        for index,agent in enumerate(model.predators):
            yield dict(agent_id=agent.unique_id,role='shark',x=float(agent.position[0]),y=float(agent.position[1]),
                       heading=float(agent.heading),vx=None,vy=None,fright=None,remaining=None,
                       target_id=int(model.targets[index]))

    def summary(self):
        model=self.core
        return dict(population=len(model.flock),predators=len(model.predators),elapsed=float(model.elapsed))

    def raw_frame(self):
        return self.core.raw_frame()
