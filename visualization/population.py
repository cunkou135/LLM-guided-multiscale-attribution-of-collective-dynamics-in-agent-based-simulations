"""Actual Covasim people/contact frames for the browser Canvas, never an engine."""
import base64
from datetime import date, timedelta
from functools import lru_cache
import hashlib
import json
from pathlib import Path

import networkx as nx
import numpy as np
import solara

from simulations.common.trajectory_api import Trajectory

STATES = {'susceptible': ('易感', '#7da9ae'), 'exposed': ('暴露', '#e0b868'),
          'infectious': ('传染', '#f28a63'), 'recovered': ('恢复', '#70c5b0'),
          'dead': ('死亡', '#747b8b'), 'other': ('未分类', '#cbd5e1')}
LAYERS = {'h': ('家庭', '#687c91'), 's': ('学校', '#9d87b1'),
          'w': ('工作场所', '#6a9f9e'), 'c': ('社区', '#c0ac8d')}


def population_settings(path='configs/population.yaml'):
    import yaml
    settings=yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    expected={'height','max_edges','pulse_ms','layout_seed','layout_iterations','recent_steps'}
    if not isinstance(settings,dict) or set(settings)!=expected or any(type(value) is not int for value in settings.values()):
        raise ValueError('Invalid population display configuration')
    if not 400<=settings['height']<=1200 or not 0<=settings['max_edges']<=20000 or not 100<=settings['pulse_ms']<=10000 or settings['layout_iterations']<1 or settings['recent_steps']<1:
        raise ValueError('Invalid population display dimensions, edge cap or animation settings')
    return settings


def disease_state(row):
    # Infectious is a subset of exposed; diagnosis/quarantine are overlays.
    for name in ('dead', 'recovered', 'infectious', 'exposed', 'susceptible'):
        if row[name]:
            return name
    return 'other'


def _edges(contacts):
    if contacts.empty:
        return []
    data = contacts.assign(a=np.minimum(contacts.agent_id, contacts.partner_id),
                           b=np.maximum(contacts.agent_id, contacts.partner_id))
    data = data.drop_duplicates(['a', 'b', 'layer']).sort_values(['layer', 'a', 'b'])
    return [[int(r.a), int(r.b), str(r.layer)] for r in data.itertuples()]


@lru_cache(maxsize=8)
def population_layout(directory, seed=17, iterations=40):
    """One fixed layout per run, using only the initial recorded contact graph."""
    t = Trajectory(directory)
    initial = t.available_steps()[0]
    ids = sorted(map(int, t.read_snapshot(initial).agent_id))
    edges = _edges(t.read('contacts', start=initial, end=initial))
    households = nx.Graph()
    households.add_nodes_from(ids)
    households.add_edges_from((a, b) for a, b, layer in edges if layer == 'h')
    groups = sorted((sorted(group) for group in nx.connected_components(households)), key=lambda group: group[0])
    membership = {uid: index for index, group in enumerate(groups) for uid in group}
    graph = nx.Graph()
    graph.add_nodes_from(range(len(groups)))
    # Household clusters plus actual school/workplace relations. Community
    # edges are displayed, but do not crowd the stable initial layout.
    for a, b, layer in edges:
        if layer in ('s', 'w') and membership[a] != membership[b]:
            u, v = membership[a], membership[b]
            graph.add_edge(u, v, weight=graph.get_edge_data(u, v, {}).get('weight', 0)+1)
    # Pack disconnected social components separately. A single spring layout
    # would send isolated households outward and collapse most people centrally.
    components = sorted(nx.connected_components(graph),
                        key=lambda group: (-sum(len(groups[i]) for i in group), min(group)))
    weights = [sum(len(groups[i]) for i in group) for group in components]
    boxes = {}
    def pack(indices, bounds):
        if len(indices)==1:
            boxes[indices[0]]=bounds
            return
        total=sum(weights[i] for i in indices)
        prefix=0;split=1
        for count,index in enumerate(indices[:-1],1):
            prefix+=weights[index];split=count
            if prefix>=total/2:
                break
        fraction=sum(weights[i] for i in indices[:split])/total
        x0,y0,x1,y1=bounds
        if (x1-x0)*1.8 >= y1-y0:
            cut=x0+(x1-x0)*fraction
            pack(indices[:split],(x0,y0,cut,y1));pack(indices[split:],(cut,y0,x1,y1))
        else:
            cut=y0+(y1-y0)*fraction
            pack(indices[:split],(x0,y0,x1,cut));pack(indices[split:],(x0,cut,x1,y1))
    if components:
        pack(list(range(len(components))),(-1.,-1.,1.,1.))
    rng = np.random.default_rng(seed)  # Display RNG, independent of Covasim.
    positions = {}
    for component_index,component in enumerate(components):
        centers = nx.spring_layout(graph.subgraph(sorted(component)),seed=seed+component_index,
                                   iterations=iterations,weight='weight')
        local = {}
        for index in sorted(component):
            group=groups[index]
            phase = rng.uniform(0, 2*np.pi)
            for rank, uid in enumerate(group):
                angle = phase + rank * 2.399963229728653
                radius = .014*np.sqrt(rank+1)
                local[uid] = np.asarray(centers[index]) + radius*np.array([np.cos(angle), np.sin(angle)])
        local_ids=sorted(local)
        coordinates=np.asarray([local[uid] for uid in local_ids])
        low,high=coordinates.min(axis=0),coordinates.max(axis=0)
        unit=(coordinates-low)/np.maximum(high-low,1e-9)
        unit[:,high-low<1e-9]=.5
        x0,y0,x1,y1=boxes[component_index]
        target=np.array([x0,y0])+(unit*.94+.03)*np.array([x1-x0,y1-y0])
        positions.update(zip(local_ids,target))
    coordinates=np.asarray([positions[uid] for uid in ids])
    nodes = [[uid, float(x), float(y)] for uid, (x,y) in zip(ids, coordinates)]
    return {'run_id': t.metadata()['run_id'], 'nodes': nodes, 'seed': seed,
            'algorithm': 'component-packed initial household / school-work spring layout / fixed member offsets',
            'iterations': iterations, 'networkx': nx.__version__,
            'sha256': hashlib.sha256(json.dumps(nodes).encode()).hexdigest()}


def population_frame(trajectory, step, selected_uid=-1, recent_steps=3):
    states = trajectory.read_snapshot(step).sort_values('agent_id')
    contacts = trajectory.read('contacts', start=step, end=step)
    events = trajectory.read('events', start=step, end=step)
    infection = events.loc[events.event_type == 'infection']
    nodes = []
    flags = ('susceptible','exposed','infectious','symptomatic','severe','critical',
             'tested','diagnosed','recovered','dead','known_contact','quarantined')
    for row in states.to_dict('records'):
        node = {'id': int(row['agent_id']), 'age': float(row['age']), 'sex': int(row['sex']),
                'state': disease_state(row), **{key: bool(row[key]) for key in flags}}
        nodes.append(node)
    recent = []
    if selected_uid >= 0 and recent_steps > 1:
        prior = trajectory.read('contacts', start=max(0, step-recent_steps+1), end=step-1, agent_id=selected_uid)
        recent = _edges(prior)
    day = int(states.simulation_day.iloc[0]) if len(states) else step-1
    start = date.fromisoformat(trajectory.configuration()['parameters']['start_day'])
    transmissions = [{'source': int(row.partner_id) if not np.isnan(row.partner_id) else None,
                      'target': int(row.agent_id), 'layer': row.layer,
                      'event_index': int(row.event_index), 'native_day': int(row.simulation_day)} for row in infection.itertuples()]
    return {'run_id': trajectory.metadata()['run_id'], 'step': int(step), 'native_day': day,
            'date': str(start+timedelta(days=day)) if day >= 0 else '初始化',
            'nodes': nodes, 'contacts': _edges(contacts), 'contact_records': len(contacts),
            'recent_contacts': recent, 'recent_steps': recent_steps,
            'infections': transmissions, 'state_legend': STATES, 'layer_legend': LAYERS,
            'state_sha256': hashlib.sha256(json.dumps(nodes, sort_keys=True).encode()).hexdigest()}


@solara.component_vue('population.vue')
def PopulationScene(frame: dict, scene_layout: dict, selected_uid: int=-1, on_selected_uid=None,
                    height: int=650, max_edges: int=1400, pulse_ms: int=1200,
                    event_capture=None):
    """Canvas interaction and pulse animation run locally in the browser."""
    pass


def save_browser_capture(trajectory, payload):
    """Save a PNG captured from the actual displayed browser Canvas."""
    if payload['run_id'] != trajectory.metadata()['run_id']:
        raise ValueError('Capture run does not match the displayed trajectory')
    step = int(payload['step'])
    trajectory.read_snapshot(step)  # An actual saved step is required.
    uri = payload['png']
    if not uri.startswith('data:image/png;base64,') or len(uri) > 16_000_000:
        raise ValueError('Invalid browser PNG capture')
    directory = trajectory.directory / 'ui_capture'
    directory.mkdir(exist_ok=True)
    name = directory / f'step_{step:06d}.png'
    name.write_bytes(base64.b64decode(uri.split(',',1)[1], validate=True))
    metadata = {key: value for key,value in payload.items() if key != 'png'}
    metadata.update(capture_type='actual_browser_canvas', png_sha256=hashlib.sha256(name.read_bytes()).hexdigest())
    name.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return name


def make_capture_gif(directory, output, start, end, duration=450):
    from PIL import Image
    directory, output = Path(directory), Path(output)
    images, records = [], []
    for step in range(start, end+1):
        name = directory / f'step_{step:06d}.png'
        record = json.loads(name.with_suffix('.json').read_text(encoding='utf-8'))
        if record['capture_type'] != 'actual_browser_canvas' or record['step'] != step or record['native_day'] != step-1:
            raise ValueError('GIF requires consecutive actual native-day browser captures')
        if hashlib.sha256(name.read_bytes()).hexdigest() != record['png_sha256']:
            raise ValueError('Capture hash mismatch')
        records.append(record)
        with Image.open(name) as image:
            images.append(image.convert('RGB').copy())
    if len({r['run_id'] for r in records}) != 1 or end-start < 9:
        raise ValueError('Use at least ten consecutive days from the same run')
    output.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(output, save_all=True, append_images=images[1:], duration=duration, loop=0)
    output.with_suffix('.json').write_text(json.dumps({'source':'actual browser Canvas captures', 'frames':records}, indent=2), encoding='utf-8')
    return output


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--capture-dir',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--start',type=int,required=True)
    parser.add_argument('--end',type=int,required=True)
    args=parser.parse_args()
    print(make_capture_gif(args.capture_dir,args.output,args.start,args.end))
