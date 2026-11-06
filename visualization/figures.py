"""Descriptive views and publication exports derived only from saved trajectories."""
import hashlib
import json
from pathlib import Path
import subprocess

import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.colors import ListedColormap, BoundaryNorm
import numpy as np
import pandas as pd
import yaml

from simulations.common.trajectory_api import Trajectory

FIGURE_VERSION = '2.0.0'
COLORS = {'vacant': '#f2f2ef', 'a': '#0072B2', 'b': '#E69F00',
          'exposed': '#D55E00', 'infectious': '#CC79A7', 'recovered': '#009E73'}
LAYERS = {'h': 'Household', 's': 'School', 'w': 'Workplace', 'c': 'Community',
          'l': 'Long-term care', 'importation': 'Importation', 'seed_infection': 'Initial seeds'}
INTERVENTIONS = {'test_prob': 'Testing', 'contact_tracing': 'Contact tracing',
                 'change_beta': 'Transmission change', 'clip_edges': 'Contact reduction'}


def intervention_schedule(configuration):
    """Configured native dates, including date strings and multi-day changes."""
    from datetime import date
    origin = date.fromisoformat(configuration['parameters']['start_day'])
    schedule = []
    for index, item in enumerate(configuration['parameters']['interventions']):
        days = item.get('days', item.get('start_day', 0))
        for day in days if isinstance(days, list) else [days]:
            if day is None:
                day = 0
            if isinstance(day, str):
                day = (date.fromisoformat(day)-origin).days
            schedule.append({'configuration_index': index, 'type': item['type'], 'label': INTERVENTIONS[item['type']],
                             'native_day': int(day), 'recorded_step': int(day)+1})
    return schedule


def figure_config(path='configs/figures.yaml'):
    c = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    expected = {'aspect','width_inches','dpi','formats','network_max_nodes','network_root',
                'font_size','window_start','window_end','age_bins','display_seed'}
    if not isinstance(c, dict) or set(c) != expected:
        raise ValueError('Invalid figure configuration fields')
    if c['aspect'] not in ('4:3', '16:9') or not 3 <= c['width_inches'] <= 20:
        raise ValueError('Invalid publication size')
    if not set(c['dpi']) <= {300, 600} or not c['dpi'] or not set(c['formats']) <= {'png', 'svg'}:
        raise ValueError('Choose PNG/SVG and 300/600 DPI')
    if type(c['network_max_nodes']) is not int or c['network_max_nodes'] < 2 or c['font_size'] < 6 or len(c['age_bins']) < 2 or any(b <= a for a, b in zip(c['age_bins'], c['age_bins'][1:])):
        raise ValueError('Invalid figure font, network limit or age bins')
    if type(c['window_start']) is not int or c['window_start'] < 0 or (c['window_end'] is not None and (type(c['window_end']) is not int or c['window_end'] < c['window_start'])):
        raise ValueError('Invalid time window')
    if c['network_root'] is not None and (type(c['network_root']) is not int or c['network_root'] < 0):
        raise ValueError('Invalid network root')
    if type(c['display_seed']) is not int:
        raise ValueError('display_seed must be integer')
    return c


def grid_values(states, parameters, value='kind'):
    width, height = parameters['width'], parameters['height']
    matrix = np.full((height, width), np.nan if value != 'kind' else 0.)
    values = states.kind.to_numpy() + 1 if value == 'kind' else states[value].to_numpy()
    matrix[states.y.astype(int), states.x.astype(int)] = values
    return matrix


def schematic_curves(trajectory):
    model = trajectory.read('model_states').sort_values('step')
    events = trajectory.read('events')
    moves = events.groupby('step').moved.sum() if 'moved' in events else pd.Series(dtype=int)
    model['happy_fraction'] = model.happy / model.population.replace(0, np.nan)
    model['move_count'] = model.step.map(moves).fillna(0).astype(int)
    model['same_fraction'] = model.same_neighbors / model.neighbors.replace(0, np.nan)
    return model


def infection_view(trajectory, start, end, max_nodes, root=None):
    """A deterministically filtered local graph of recorded successful infections."""
    events = trajectory.read('events', start=start, end=end)
    infection = events.loc[events.event_type == 'infection'].sort_values('event_index')
    edges = infection.loc[infection.partner_id.notna()].copy()
    adjacency = {}
    for row in edges.itertuples():
        source, target = int(row.partner_id), int(row.agent_id)
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    if root is None:
        root = int(edges.iloc[0].partner_id) if len(edges) else int(infection.iloc[0].agent_id) if len(infection) else None
    root = int(root) if root is not None else None
    depths, queue = ({root: 0}, [root]) if root is not None else ({}, [])
    while queue and len(depths) < max_nodes:
        node = queue.pop(0)
        for neighbor in sorted(adjacency.get(node, ())):
            if neighbor not in depths and len(depths) < max_nodes:
                depths[neighbor] = depths[node] + 1
                queue.append(neighbor)
    selected = edges.loc[edges.agent_id.isin(depths) & edges.partner_id.isin(depths)]
    positions = {}
    for depth in sorted(set(depths.values())):
        nodes = sorted(n for n, d in depths.items() if d == depth)
        for index, node in enumerate(nodes):
            positions[node] = (depth, (index-(len(nodes)-1)/2) / max(1, len(nodes)))
    return infection, selected, positions, root


def age_composition(states, bins):
    groups = pd.cut(states.age, bins=bins, right=False)
    if groups.isna().any():
        raise ValueError('Configured age bins do not cover all recorded people')
    # These four states are disjoint for this native non-rescaling profile.
    return states.groupby(groups, observed=False)[['susceptible', 'exposed', 'recovered', 'dead']].sum()


def _axis_style(axis):
    axis.spines[['top', 'right']].set_visible(False)
    axis.tick_params(length=3, width=.6)


def interactive_grid(trajectory, step, *, similarity=False, unhappy=False, recent_steps=3, height=520):
    import plotly.graph_objects as go
    states = trajectory.read_snapshot(step)
    p = trajectory.configuration()['parameters']
    if similarity:
        states = states.assign(similarity=states.same_neighbors / states.neighbors.replace(0, np.nan))
        states['similarity'] = states.similarity.fillna(0.)
        trace = go.Heatmap(z=grid_values(states, p, 'similarity'), zmin=0, zmax=1, colorscale='Viridis',
                           colorbar=dict(title='Same-neighbor<br>fraction', thickness=12))
    else:
        trace = go.Heatmap(z=grid_values(states, p), zmin=0, zmax=2,
                           colorscale=[[0,'#102936'],[.249,'#102936'],[.25,COLORS['a']],[.749,COLORS['a']],[.75,COLORS['b']],[1,COLORS['b']]],
                           colorbar=dict(tickvals=[0,1,2], ticktext=['Vacant','Group A','Group B'], thickness=12))
    figure = go.Figure(trace)
    if unhappy:
        subset = states.loc[~states.happy]
        figure.add_scatter(x=subset.x, y=subset.y, mode='markers', name='Unsatisfied',
                           marker=dict(symbol='x', color='#343434', size=4))
    if recent_steps:
        events = trajectory.read('events', start=max(1,step-recent_steps+1), end=step)
        moves = events.loc[events.moved]
        figure.add_scatter(x=moves.x_after, y=moves.y_after, mode='markers', name=f'Moved in last {recent_steps} sweeps',
                           marker=dict(symbol='circle-open', color='#333333', size=7, line=dict(width=1)))
    figure.update_layout(template='plotly_dark',paper_bgcolor='#091b25',plot_bgcolor='#091b25', height=height, margin=dict(l=35,r=20,t=15,b=30),
                         xaxis=dict(title='Residential x', range=[-.5,p['width']-.5], constrain='domain', autorange=False),
                         yaxis=dict(title='Residential y', range=[-.5,p['height']-.5], constrain='domain', autorange=False, scaleanchor='x', scaleratio=1),
                         uirevision=trajectory.directory.name, dragmode='pan', legend=dict(orientation='h', y=-.16),
                         font=dict(family='Georgia, Microsoft YaHei, sans-serif',size=11,color='#9ac5c9'))
    if height < 300:
        figure.update_traces(showscale=False, selector=dict(type='heatmap'))
        figure.update_layout(margin=dict(l=35,r=5,t=5,b=30))
    return figure


def interactive_schelling_curves(trajectory, step):
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go
    data = schematic_curves(trajectory)
    figure = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.16)
    figure.add_trace(go.Scatter(x=data.step, y=data.happy_fraction, name='Satisfied fraction', line=dict(color=COLORS['a'])), row=1, col=1)
    figure.add_trace(go.Scatter(x=data.step, y=data.move_count, name='Actual relocations', line=dict(color=COLORS['b'],dash='dash')), row=2,col=1)
    figure.add_vline(x=step, line_width=1, line_dash='dot', line_color='#555555')
    figure.update_yaxes(range=[0,1.02], title_text='Satisfied', row=1,col=1)
    figure.update_yaxes(title_text='Moves', rangemode='tozero', row=2,col=1)
    figure.update_xaxes(title_text='Recorded sweep', row=2,col=1)
    figure.update_layout(template='plotly_white', height=330, margin=dict(l=55,r=12,t=25,b=35), legend=dict(orientation='h',y=1.14))
    return figure


def interactive_covasim(trajectory, step, settings, start=0):
    import plotly.graph_objects as go
    model = trajectory.read('model_states').sort_values('step')
    evolution = go.Figure()
    for state, color, dash in (('exposed',COLORS['exposed'],'solid'),('infectious',COLORS['infectious'],'dash'),('recovered',COLORS['recovered'],'dot')):
        evolution.add_scatter(x=model.step, y=model[state], name=state.capitalize(), line=dict(color=color,dash=dash))
    evolution.add_vline(x=step, line_color='#333333', line_dash='dot', line_width=1)
    schedule = intervention_schedule(trajectory.configuration())
    for point in sorted({item['recorded_step'] for item in schedule}):
        label = ' + '.join(item['label'] for item in schedule if item['recorded_step'] == point)
        evolution.add_vline(x=point,line_width=.7,line_dash='dash',line_color='#bbbbbb',annotation_text=label,annotation_font_size=9)
    evolution.update_layout(template='plotly_white',height=340,margin=dict(l=45,r=15,t=35,b=35),
                            legend=dict(orientation='h',y=1.15),xaxis_title='Recorded step (native day + 1)',yaxis_title='Simulated people')
    infection,edges,positions,root=infection_view(trajectory,start,step,settings['network_max_nodes'],settings['network_root'])
    network=go.Figure()
    for row in edges.itertuples():
        x,y=positions[int(row.partner_id)];u,v=positions[int(row.agent_id)]
        # Use traces: FigureWidget annotations can linger when replaying an
        # earlier frame with no edges. Trace replacement also clears empty graphs.
        network.add_scatter(x=[x,u],y=[y,v],mode='lines+markers',
                            line=dict(color='#aaaaa5',width=.8),
                            marker=dict(symbol=['circle','arrow'],size=[0,7],color='#aaaaa5',angleref='previous',standoff=4),
                            showlegend=False,hoverinfo='skip')
    if positions:
        ids=list(positions)
        network.add_scatter(x=[positions[i][0] for i in ids],y=[positions[i][1] for i in ids],mode='markers',
                            text=[f'Resident {i}' for i in ids],hovertemplate='%{text}<extra></extra>',
                            marker=dict(color=COLORS['a'],size=9,line=dict(color='white',width=1)),showlegend=False)
    network.update_layout(template='plotly_white',height=340,title=f'Recorded transmissions · root {root} · ≤{settings["network_max_nodes"]} nodes',
                          margin=dict(l=25,r=15,t=45,b=30),xaxis=dict(title='Local graph depth',showgrid=False),yaxis=dict(visible=False))
    counts=infection.layer.fillna('Seed / import').value_counts().sort_index()
    layers=go.Figure(go.Bar(x=counts.to_numpy(),y=[LAYERS.get(k,k) for k in counts.index],orientation='h',marker_color=COLORS['a']))
    layers.update_layout(template='plotly_white',height=300,title=f'Recorded infections · steps {start}–{step}',
                         margin=dict(l=105,r=15,t=45,b=35),xaxis_title='Successful infection events')
    age=age_composition(trajectory.read_snapshot(step),settings['age_bins'])
    ages=go.Figure()
    for state,color in (('susceptible','#c9ced1'),('exposed',COLORS['exposed']),('recovered',COLORS['recovered']),('dead','#333333')):
        ages.add_bar(x=[f'{int(i.left)}–{int(i.right)}' for i in age.index],y=age[state],name=state.capitalize(),marker_color=color)
    ages.update_layout(template='plotly_white',height=300,barmode='stack',title='Age × disjoint disease states',
                       margin=dict(l=45,r=15,t=45,b=40),legend=dict(orientation='h',y=-.25),xaxis_title='Age (years)',yaxis_title='People')
    return evolution,network,layers,ages


def publication_figure(trajectory, settings, end_step=None):
    c = trajectory.configuration()
    steps = trajectory.available_steps()
    end = settings['window_end'] if end_step is None else end_step
    end = steps[-1] if end is None else end
    if end not in steps:
        raise ValueError('Publication endpoint must be an actually recorded step')
    start = settings['window_start']
    selected_steps = [s for s in steps if start <= s <= end]
    if not selected_steps:
        raise ValueError('No recorded states in requested window')
    width = settings['width_inches']
    height = width * (3/4 if settings['aspect'] == '4:3' else 9/16)
    style = {'font.family': 'DejaVu Sans', 'font.size': settings['font_size'],
             'axes.titlesize': settings['font_size']+1, 'axes.labelsize': settings['font_size'],
             'axes.linewidth': .6, 'lines.linewidth': 1.1, 'legend.fontsize': settings['font_size']-1,
             'svg.fonttype': 'none', 'svg.hashsalt': 'abms-lab-publication-v2'}
    with mpl.rc_context(style):
        fig = Figure(figsize=(width, height), constrained_layout=True, facecolor='white')
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        FigureCanvasAgg(fig)
        axes = fig.subplots(2, 2).ravel()
        data = {'model': c['model'], 'window': [start, end], 'recorded_steps': selected_steps}
        if c['model']=='fish':
            snapshots=[selected_steps[0],selected_steps[len(selected_steps)//2],selected_steps[-1]]
            states=trajectory.read('agent_states')
            padding=max(1.,max(states.x.max()-states.x.min(),states.y.max()-states.y.min())*.05)
            bounds=(states.x.min()-padding,states.x.max()+padding,states.y.min()-padding,states.y.max()+padding)
            for axis,step,title in zip(axes[:3],snapshots,('Initial','Intermediate','Final / selected')):
                sample=trajectory.read_snapshot(step)
                fish=sample.loc[sample.role=='fish'];sharks=sample.loc[sample.role=='shark']
                axis.scatter(fish.x,fish.y,s=1.2,c=['#27776c' if v==0 else '#D55E00' if v==1 else '#bf8132' for v in fish.fright],linewidths=0,rasterized=True)
                axis.scatter(sharks.x,sharks.y,s=18,marker='>',color='#D55E00',edgecolors='white',linewidths=.4)
                axis.set(title=f'{title} | step {step}',xlabel='Model x',ylabel='Model y',xlim=bounds[:2],ylim=bounds[2:])
                axis.set_aspect('equal',adjustable='box')
            ids=sorted(map(int,states.loc[states.role=='fish','agent_id'].unique()))
            chosen=ids[::max(1,len(ids)//7)][:7]
            for uid in chosen:
                path=states.loc[(states.agent_id==uid)&(states.step>=start)&(states.step<=end)].sort_values('step')
                axes[3].plot(path.x,path.y,label=f'UID {uid}',linewidth=.8)
            axes[3].set(title='Recorded individual paths',xlabel='Model x',ylabel='Model y',xlim=bounds[:2],ylim=bounds[2:])
            axes[3].set_aspect('equal',adjustable='box');axes[3].legend(frameon=False,fontsize=6,ncol=2)
            data.update(snapshot_steps=snapshots,fish_count=c['parameters']['population']['count'],
                        shark_count=c['parameters']['fish']['N_p'],path_agent_ids=chosen,
                        paths=states.loc[states.agent_id.isin(chosen)&(states.step>=start)&(states.step<=end),['step','agent_id','x','y']].to_dict('records'))
        elif c['model'].startswith('schelling'):
            snapshots = [selected_steps[0], selected_steps[len(selected_steps)//2], selected_steps[-1]]
            cmap = ListedColormap([COLORS['vacant'], COLORS['a'], COLORS['b']])
            norm = BoundaryNorm([-.5, .5, 1.5, 2.5], 3)
            for axis, step, title in zip(axes[:3], snapshots, ('Initial', 'Intermediate', 'Final / selected')):
                states = trajectory.read_snapshot(step)
                axis.imshow(grid_values(states, c['parameters']), origin='lower', cmap=cmap, norm=norm,
                            interpolation='nearest', rasterized=True)
                axis.set(title=f'{title} | step {step}', xlabel='Residential x', ylabel='Residential y')
                axis.set_xticks([0, c['parameters']['width']-1]); axis.set_yticks([0, c['parameters']['height']-1])
            curves = schematic_curves(trajectory)
            full_end = int(curves.step.max())
            full_moves_max = curves.move_count.max()
            curves = curves.loc[(curves.step >= start) & (curves.step <= end)]
            axis = axes[3]
            axis.plot(curves.step, curves.happy_fraction, color=COLORS['a'], label='Satisfied fraction')
            axis.set(xlabel='Completed sweep', ylabel='Satisfied fraction', ylim=(0, 1.02), xlim=(0, max(1, full_end)))
            # A separate inset keeps different units off a misleading dual y axis.
            inset = axis.inset_axes([.12, .15, .72, .30])
            inset.plot(curves.step, curves.move_count, color=COLORS['b'], linestyle='--')
            inset.set(ylabel='Moves', xlim=(0, max(1, full_end)), ylim=(0, max(1, full_moves_max*1.05)))
            inset.tick_params(labelsize=6)
            inset.xaxis.label.set_size(6); inset.yaxis.label.set_size(6)
            _axis_style(inset)
            data.update(snapshot_steps=snapshots, snapshot_population=[len(trajectory.read_snapshot(s)) for s in snapshots],
                        curves=curves[['step', 'happy_fraction', 'move_count', 'same_fraction']].to_dict('records'))
            from matplotlib.patches import Patch
            fig.legend(handles=[Patch(color=COLORS['vacant'], label='Vacant'), Patch(color=COLORS['a'], label='Group A'),
                                Patch(color=COLORS['b'], label='Group B')], loc='outside lower center', ncol=3, frameon=False)
        else:
            all_model = trajectory.read('model_states').sort_values('step')
            model = all_model.loc[(all_model.step >= start) & (all_model.step <= end)]
            for state, color, dash in (('exposed', COLORS['exposed'], '-'), ('infectious', COLORS['infectious'], '--'), ('recovered', COLORS['recovered'], ':')):
                axes[0].plot(model.step, model[state], color=color, linestyle=dash, label=state.capitalize())
            schedule = intervention_schedule(c)
            for point in sorted({item['recorded_step'] for item in schedule}):
                if start <= point <= end:
                    axes[0].axvline(point, color='#666666', linewidth=.7, linestyle=':')
            axes[0].set(title='Disease states (overlap)', xlabel='Recorded step', ylabel='Simulated people',
                        xlim=(0, max(1, int(all_model.step.max()))), ylim=(0, max(1, all_model[['exposed','infectious','recovered']].to_numpy().max()*1.1)))
            axes[0].legend(frameon=False)
            infection, edges, positions, root = infection_view(trajectory, start, end, settings['network_max_nodes'], settings['network_root'])
            network = axes[1]
            for row in edges.itertuples():
                x, y = positions[int(row.partner_id)]; u, v = positions[int(row.agent_id)]
                network.annotate('', xy=(u, v), xytext=(x, y), arrowprops={'arrowstyle': '->', 'color': '#9b9b97', 'lw': .55, 'shrinkA': 2, 'shrinkB': 2})
            if positions:
                network.scatter(*np.array(list(positions.values())).T, s=16, color=COLORS['a'], edgecolors='white', linewidths=.4, zorder=3)
            network.set(title=f'Recorded transmission | root {root}', xlabel=f'Local depth | limit {settings["network_max_nodes"]} people', yticks=[])
            network.margins(.12)
            counts = infection.layer.fillna('Seed / import').value_counts().sort_index()
            labels = [LAYERS.get(k, k) for k in counts.index]
            axes[2].barh(labels, counts.to_numpy(), color=COLORS['a'])
            axes[2].set(title=f'Infection layers | steps {start}–{end}', xlabel='Recorded infection events')
            states = trajectory.read_snapshot(end)
            age = age_composition(states, settings['age_bins'])
            bottom = np.zeros(len(age))
            for state, color in (('susceptible', '#c9ced1'), ('exposed', COLORS['exposed']), ('recovered', COLORS['recovered']), ('dead', '#333333')):
                axes[3].bar(np.arange(len(age)), age[state].to_numpy(), bottom=bottom, color=color, label=state.capitalize(), width=.8)
                bottom += age[state].to_numpy()
            axes[3].set_xticks(np.arange(len(age)), [f'{int(i.left)}–{int(i.right)}' for i in age.index], rotation=35)
            axes[3].set(title=f'Age × disease state | step {end}', xlabel='Age (years)', ylabel='Simulated people',
                        ylim=(0, max(1, float(bottom.max())*1.08)))
            fig.legend(*axes[3].get_legend_handles_labels(), loc='outside lower center', ncol=4, frameon=False)
            data.update(curves=model[['step','exposed','infectious','recovered']].to_dict('records'), intervention_schedule=schedule,
                        network_root=root, network_root_rule='explicit root or earliest recorded infector in window', network_node_ids=sorted(positions),
                        network_edges=edges[['event_index','agent_id','partner_id','layer','step']].to_dict('records'),
                        layer_counts=dict(zip(labels, map(int, counts))), age_counts=age.reset_index().astype({'age': str}).to_dict('records'))
        for index, axis in enumerate(axes):
            _axis_style(axis)
        fig.canvas.draw()
        for index, axis in enumerate(axes):
            position = axis.get_position()
            fig.text(position.x0-.045, position.y1+.014, 'abcd'[index], fontsize=10, fontweight='bold', va='bottom')
        return fig, data


def export_publication(run_directory, output_directory=None, settings_path='configs/figures.yaml', end_step=None):
    trajectory = Trajectory(run_directory)
    settings = figure_config(settings_path)
    fig, data = publication_figure(trajectory, settings, end_step=end_step)
    output = Path(output_directory) if output_directory else Path(run_directory) / 'figures'
    output.mkdir(parents=True, exist_ok=True)
    previous = output / 'figure_manifest.json'
    metadata = trajectory.metadata()
    if previous.exists() and json.loads(previous.read_text(encoding='utf-8'))['run_id'] != metadata['run_id']:
        raise ValueError('Output directory already contains another run; choose a new directory')
    with mpl.rc_context({'svg.fonttype': 'none', 'svg.hashsalt': 'abms-lab-publication-v2'}):
        for dpi in settings['dpi']:
            if 'png' in settings['formats']:
                fig.savefig(output / f'publication_{dpi}dpi.png', dpi=dpi, facecolor='white')
        if 'svg' in settings['formats']:
            fig.savefig(output / 'publication.svg', dpi=max(settings['dpi']), metadata={'Date': None, 'Creator': f'ABMS Lab {FIGURE_VERSION}'})
    (output / 'figure_data.json').write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    manifest = dict(run_id=metadata['run_id'], scenario_id=metadata['scenario_id'], scenario_version=metadata['scenario_version'],
                    scenario_sha256=metadata['scenario_sha256'], time_range=data['window'], figure_configuration=settings,
                    export_version=FIGURE_VERSION, export_commit=git.stdout.strip() if git.returncode == 0 else None,
                    export_git_dirty=bool(status.stdout.strip()) if status.returncode == 0 else None,
                    source_run_commit=metadata.get('git_commit'), source_run_git_dirty=metadata.get('git_dirty'),
                    source_fingerprints=trajectory.source_fingerprints(),
                    figure_data_sha256=hashlib.sha256((output / 'figure_data.json').read_bytes()).hexdigest())
    previous.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return output
