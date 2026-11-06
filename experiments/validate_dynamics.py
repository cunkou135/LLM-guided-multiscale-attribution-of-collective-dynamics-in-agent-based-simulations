"""Run a transparent, qualitative multi-seed dynamics check.

Results are generated, never embedded as expected values in the models.
Run: python -m experiments.validate_dynamics
"""
import json
from pathlib import Path

from simulations.common.runner import load, run
from simulations.common.trajectory_api import Trajectory


def main():
    entries = []
    for seed in (11, 22, 33):
        for homophily in (.2, .4):
            c = load('configs/schelling_standard.yaml')
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
    path = Path('results') / 'validation_dynamics.json'
    path.write_text(json.dumps(entries, indent=2), encoding='utf-8')
    print(path)


if __name__ == '__main__':
    main()
