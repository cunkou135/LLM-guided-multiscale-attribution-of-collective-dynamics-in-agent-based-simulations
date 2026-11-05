"""Mesa SolaraViz interface; the simulation itself is the headless RunSession."""
import copy
import os
from pathlib import Path

import numpy as np
import solara
from matplotlib.figure import Figure
from mesa import Model
from mesa.visualization import Slider, SolaraViz

from simulations.common.runner import RunSession, load


class VisualRun(Model):
    def __init__(self, config, primary, secondary):
        c = copy.deepcopy(config)
        if c['model'] == 'schelling':
            c['parameters'].update(homophily=primary, density=secondary)
        else:
            c['parameters'].update(beta=primary, pop_infected=int(secondary))
        super().__init__(rng=c['seed'])
        self.session = RunSession(c)
        self.history = []
        self.remember()

    def remember(self):
        m = self.session.model
        if self.session.config['model'] == 'schelling':
            summary = m.summary()
            population = summary['population']
            score = summary['happy'] / population if population else 0
            similarity = summary['same_neighbors'] / summary['neighbors'] if summary['neighbors'] else 0
            self.history.append((self.session.completed, score, similarity))
        else:
            summary = m.summary()
            self.history.append((self.session.completed, summary['infectious'], summary['diagnosed']))

    def step(self):
        if not self.session.closed:
            self.session.advance()
            self.remember()
        self.running = not self.session.closed

    def close(self):
        self.session.close()
        self.running = False


def display(model):
    session = model.session
    core = session.model
    fig = Figure(figsize=(9, 4), constrained_layout=True)
    left, right = fig.subplots(1, 2)
    if session.config['model'] == 'schelling':
        for kind, color in ((0, '#377eb8'), (1, '#e67e22')):
            for happy, marker in ((True, 'o'), (False, 'x')):
                agents = [a for a in core.agents if a.kind == kind and a.happy == happy]
                left.scatter([a.cell.coordinate[0] for a in agents], [a.cell.coordinate[1] for a in agents], c=color, marker=marker, s=30, label=f'{kind} {"happy" if happy else "unhappy"}')
        p = session.config['parameters']
        left.set(xlim=(-.5, p['width']-.5), ylim=(-.5, p['height']-.5), title='Residents (empty = vacant)', aspect='equal')
        left.legend(fontsize=7)
        titles = ('Happy fraction', 'Same-kind neighbor fraction')
    else:
        summary = core.summary()
        labels = ['susceptible', 'exposed', 'infectious', 'recovered', 'diagnosed', 'quarantined', 'dead']
        left.bar(labels, [summary[k] for k in labels], color='#377eb8')
        left.tick_params(axis='x', labelrotation=60)
        left.set(title='Native Covasim states (overlapping)', ylabel='Simulated people')
        titles = ('Infectious', 'Diagnosed')
    history = np.asarray(model.history)
    right.plot(history[:, 0], history[:, 1], label=titles[0])
    right.plot(history[:, 0], history[:, 2], label=titles[1])
    right.set(xlabel='Sampling step', title='Evolution')
    right.legend(fontsize=8)
    return solara.FigureMatplotlib(fig, format='png')


def status(model):
    c = model.session.config
    extra = ''
    if c['model'] == 'covasim':
        extra = f"  \n**Uncalibrated demonstration, not historical reproduction.** Potential contact edges by layer: `{model.session.model.contact_counts}`. Interventions: `{c['parameters']['interventions']}`"
    return solara.Markdown(f"**Step:** {model.session.completed}/{c['steps']}　 **Seed:** {c['seed']}　 **Parameters:** `{c['parameters']}`  \n**Run:** `{model.session.out}`" + extra)


@solara.component
def Page():
    config = load(os.environ['ABMS_CONFIG'])
    p = config['parameters']
    if config['model'] == 'schelling':
        primary, secondary = p['homophily'], p['density']
        names = ('Homophily', 'Density')
    else:
        primary, secondary = p['beta'], p['pop_infected']
        names = ('Transmission beta', 'Initial infections')
    initial = solara.use_memo(lambda: VisualRun(config, primary, secondary), [])
    reactive = solara.use_reactive(initial)
    current = reactive.value

    def close_when_replaced():
        return current.close

    solara.use_effect(close_when_replaced, [current])
    params = {'config': config, 'primary': Slider(names[0], primary, 0, 1 if config['model'] == 'schelling' else .1, .05 if config['model'] == 'schelling' else .001), 'secondary': Slider(names[1], secondary, 0, 1 if config['model'] == 'schelling' else p['pop_size'], .05 if config['model'] == 'schelling' else 1)}
    SolaraViz(reactive, components=[display, status], model_params=params, name=f"ABMS Lab — {config['model']}")
