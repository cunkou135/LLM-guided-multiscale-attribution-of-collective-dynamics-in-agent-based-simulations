"""Compare equivalent descriptive metrics with a NetLogo BehaviorSpace CSV."""
import argparse
import json
from pathlib import Path

import pandas as pd
from simulations.common.runner import load, run
from simulations.common.trajectory_api import Trajectory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('netlogo_csv')
    args = parser.parse_args()
    table = pd.read_csv(args.netlogo_csv, skiprows=6)
    entries = []
    for _, rows in table.groupby('[run number]', sort=True):
        first, last = rows.iloc[0], rows.iloc[-1]
        seed = int(first.iloc[5])
        threshold = float(first['%-similar-wanted']) / 100
        c = load('configs/schelling.yaml')
        c['seed'], c['steps'] = seed, 40
        c['parameters'].update(width=20, height=20, torus=True, density=.8, minority_pc=.5, homophily=threshold)
        output = run(c)
        states = Trajectory(output).read('model_states')
        a, b = states.iloc[0], states.iloc[-1]
        def mesa(row):
            return dict(step=int(row.step), unhappy=float(1-row.happy/row.population), similarity=float(row.same_neighbors/row.neighbors))
        def netlogo(row):
            return dict(step=int(row['[step]']), unhappy=float(row['percent-unhappy']/100), similarity=float(row['percent-similar']/100))
        entries.append(dict(seed=seed, threshold=threshold, mesa_run_id=output.name,
                            mesa_initial=mesa(a), mesa_final=mesa(b), netlogo_initial=netlogo(first), netlogo_final=netlogo(last)))
    target = Path('results/netlogo_mesa_summary.json')
    target.write_text(json.dumps(entries, indent=2), encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
