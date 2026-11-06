"""Display-only fish packets from the unified saved trajectory interface."""
from pathlib import Path

import numpy as np
import solara
import yaml


def fish_packet(trajectory,step):
    raw=trajectory.read_frame(step)
    d=raw['decisions']
    agents=[[uid,*position,heading,0,int(d['d'][i])+2*int(d['s'][i])]
            for i,(uid,position,heading) in enumerate(zip(raw['ids'],raw['positions'],raw['headings']))]
    predators=[[uid,*position,heading] for uid,position,heading in zip(raw['shark_ids'],raw['shark_positions'],raw['shark_headings'])]
    return dict(run_id=trajectory.metadata()['run_id'],step=raw['step'],time=raw['time'],
                agents=agents,predators=predators,center=np.mean(raw['positions'],axis=0).tolist(),
                decisions={key:d[key] for key in ('d','s','r','o','kappa','phi')},
                fish=trajectory.configuration()['parameters']['fish'])


def fish_display(path='configs/fish_display.yaml'):
    settings=yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(settings,dict) or not 300<=settings.get('height',0)<=1200 or settings.get('zoom',0)<=0:
        raise ValueError('Invalid fish display settings')
    return settings


@solara.component_vue('fish.vue')
def FishScene(frame:dict,settings:dict,playing:bool=False,event_capture=None):
    pass
