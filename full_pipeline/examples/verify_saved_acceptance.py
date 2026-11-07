"""Independent numerical spot checks for the six saved live-acceptance definitions.

This is NOT an indicator library used by the workflow or a substitute LLM result.
It never executes generated source. It checks existing Parquet observations against
the six unchanged mathematical definitions actually returned in this acceptance.
"""
import argparse
import json
from pathlib import Path
import sys

import networkx as nx
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from causal_graph.io import digest, read_json, save_json
from simulations.common.trajectory_api import Trajectory
from full_pipeline.main import filesystem_path
from full_pipeline.validators import validate_stage1


def verify(experiment):
    root = filesystem_path(experiment); graph = read_json(root / 'stage1_graph.json'); validate_stage1(graph)
    model = graph['provenance']['scenario']['model']; records = graph['provenance']['run_records']
    checks = []
    for record in [records[0], records[-1]] if len(records) > 1 else records:
        trajectory = Trajectory(record['directory']); axis = trajectory.available_steps()
        measured = {n['node_id']: pd.read_parquet(n['execution'][record['run_id']]['series_file']) for n in graph['nodes']}
        for step in sorted({axis[0], axis[1], axis[len(axis) // 2], axis[-1]}):
            states = trajectory.read('agent_states', start=step, end=step)
            contacts = trajectory.read('contacts', start=step, end=step)
            if model == 'fish':
                fish = states.loc[states.role.eq('fish')].set_index('agent_id')
                coordinates = fish[['x', 'y']].to_numpy()
                neighbors = cKDTree(coordinates).query(coordinates, k=2)[0][:, 1]
                g = nx.Graph(); g.add_nodes_from(fish.index)
                g.add_edges_from((int(a), int(b)) for a, b in contacts[['agent_id', 'partner_id']].itertuples(index=False, name=None)
                                 if a in fish.index and b in fish.index)
                covariance = np.cov(coordinates, rowvar=False, ddof=0)
                eigenvalues = np.linalg.eigvalsh(covariance)
                expected = {'fish_nn_distance_micro': dict(zip(fish.index, neighbors)),
                    'fish_contact_fragmentation_meso': 1 - max(map(len, nx.connected_components(g))) / len(fish),
                    'fish_school_elongation_macro': np.sqrt(eigenvalues[-1] / eigenvalues[0])}
            else:
                assert states.infectious.notna().all()
                infectious = set(states.loc[states.infectious.eq(True), 'agent_id'])
                valid = set(states.agent_id)
                assert contacts.agent_id.isin(valid).all() and contacts.partner_id.isin(valid).all()
                qualifying = contacts.loc[contacts.agent_id.isin(infectious) | contacts.partner_id.isin(infectious)]
                counts = qualifying.groupby('agent_id').partner_id.nunique()
                fractions = {layer: float(np.mean(frame.agent_id.isin(infectious) | frame.partner_id.isin(infectious)))
                             for layer, frame in contacts.groupby('layer')}
                active = (set(contacts.agent_id) | set(contacts.partner_id)) & infectious
                expected = {'micro_infectious_contact_degree': {i: int(counts.get(i, 0)) for i in valid},
                    'meso_layer_infectious_edge_fraction': fractions, 'macro_contact_active_infectious_count': len(active)}
            for node in graph['nodes']:
                iid = node['node_id']; frame = measured[iid].loc[lambda f: f.step.eq(step)]
                values = expected[iid]
                if 'entity_id' in frame:
                    ids = [json.loads(v)['agent_id'] for v in frame.entity_id]
                    assert set(ids) == set(values), (iid, step, 'entity set mismatch')
                    wanted = np.array([values[i] for i in ids])
                elif isinstance(values, dict):
                    wanted = np.array([values[feature.split('__')[-1]] for feature in frame.feature])
                    assert len(frame) == len(values), (iid, step, 'layer count mismatch')
                else:
                    assert len(frame) == 1, (iid, step, 'scalar shape mismatch')
                    wanted = np.array([values])
                actual = frame.value.to_numpy()
                np.testing.assert_allclose(actual, wanted, rtol=1e-10, atol=1e-10)
                checks.append({'run_id': record['run_id'], 'seed': record['seed'], 'step': step, 'indicator_id': iid,
                               'compared_values': len(actual), 'maximum_absolute_error': float(np.max(np.abs(actual - wanted)))})
    report = {'status': 'passed', 'purpose': 'independent spot checks of saved acceptance definitions, not production indicators',
              'source_graph_sha256': digest(root / 'stage1_graph.json'), 'source_checker_sha256': digest(__file__),
              'checks': checks, 'compared_values': sum(c['compared_values'] for c in checks)}
    save_json(root / 'internal/validation/independent_numeric_checks.json', report)
    print(f'{model}: {len(checks)} checks, {report["compared_values"]} actual numeric values matched')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--experiment', required=True)
    verify(parser.parse_args().experiment)
