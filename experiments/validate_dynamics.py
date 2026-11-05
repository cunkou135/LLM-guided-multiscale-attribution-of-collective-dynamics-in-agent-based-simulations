"""Run a transparent, qualitative multi-seed dynamics check.

Results are generated, never embedded as expected values in the models.
Run: python -m experiments.validate_dynamics
"""
import json
from pathlib import Path

from simulations.common.runner import load, run
from simulations.common.trajectory_api import Trajectory


def groups(opinions, gap=.02):
    values = sorted(opinions)
    return 0 if not values else 1 + sum(b - a > gap for a, b in zip(values, values[1:]))


def main():
    entries = []
    for seed in (11, 22, 33):
        for homophily in (.2, .4):
            c = load('configs/schelling.yaml')
            c['seed'], c['steps'] = seed, 40
            c['parameters']['homophily'] = homophily
            output = run(c)
            model = Trajectory(output).read('model_states')
            first, last = model.iloc[0], model.iloc[-1]
            def summarize(row):
                return {'unhappy_fraction': 1 - row.happy / row.population if row.population else None,
                        'same_neighbor_fraction': row.same_neighbors / row.neighbors if row.neighbors else None}
            entries.append(dict(model='schelling', seed=seed, homophily=homophily,
                                run_id=output.name, steps=int(last.step), initial=summarize(first), final=summarize(last)))
    for seed in (11, 22, 33):
        for epsilon in (.1, .3, .6):
            for mu in (.25, .5):
                c = load('configs/deffuant.yaml')
                c['seed'], c['steps'] = seed, 150
                c['parameters'].update(epsilon=epsilon, mu=mu)
                output = run(c)
                states = Trajectory(output).read('agent_states')
                x = states.loc[states.step == c['steps'], 'opinion']
                variance = states.groupby('step').opinion.var(ddof=0)
                entries.append(dict(model='deffuant', seed=seed, epsilon=epsilon, mu=mu,
                                    run_id=output.name, steps=c['steps'], initial_distribution='uniform_0_1',
                                    final_groups_gap_0_02=groups(x), final_variance=float(x.var(ddof=0)),
                                    variance_by_step={str(s): float(variance.loc[s]) for s in (0, 50, 100, 150)},
                                    final_min=float(x.min()), final_max=float(x.max())))
    path = Path('results') / 'validation_dynamics.json'
    path.write_text(json.dumps(entries, indent=2), encoding='utf-8')
    print(path)


if __name__ == '__main__':
    main()
