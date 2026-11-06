"""Acceptance of the twelve immutable 30d65e1 model functions, without any LLM calls.

Reviews and references below are specific audit evidence, not an indicator library.
Reference values only verify outputs; they never replace generated calculations.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.stats import entropy

from simulations.common.trajectory_api import Trajectory
from causal_graph.code_contract import analyze_access
from causal_graph.config import load_llm, load_pipeline
from causal_graph.graph_export import export_graphs
from causal_graph.inputs import assert_unchanged
from causal_graph.io import digest, now, object_digest, read_json, save_json
from causal_graph.pipeline import run_pipeline
from causal_graph.schemas import code_errors


NOTES = {
    'frag_micro_nn_distance': ('approved', 'Euclidean all-fish nearest-neighbor distance; diagonal exclusion is correct. Preserve the (step, agent_id) observation unit; no temporal or population aggregation.'),
    'frag_meso_contact_component_count': ('approved', 'Union-find on the declared undirected recorded-contact graph includes isolated fish and rejects non-fish, unmatched and self endpoints. Recorded alarm contacts are not the complete spatial-neighbor network.'),
    'frag_macro_largest_component_fraction': ('approved', 'Largest union-find component divided by recorded fish population matches the definition; zero-population is undefined.'),
    'elong_micro_axis_alignment': ('approved', 'Absolute heading projection on the first positional principal axis. Native Fish headings are radians (engine initialization uses deg2rad). np.isclose is a numerical isotropy tolerance; the original run has no affected near-isotropic frame. Keep per-fish observations.'),
    'elong_meso_local_eigen_ratio': ('approved', 'Closed undirected contact neighborhoods, sample covariance and positive-small-eigenvalue eligibility match the definition. No eligible neighborhood remains NaN. Floating-point sensitivity near degeneracy is checked against an independent reference.'),
    'elong_macro_global_eigen_ratio': ('approved', 'All-fish sample-covariance eigenvalue ratio; degenerate/small populations remain undefined. No artificial data or result constants.'),
    'sic_micro_prior_setting_degree': ('rejected', 'The mathematical definition specifies D(e) for each infection event. The function returns a per-step mean, so event-level observations and variation are discarded; the later config note does not preserve the original observation unit. It also lacks the specified negative-sentinel filter (the supplied contacts contain no negative IDs). Original code is retained and not executed.'),
    'icts_micro_quarantine_contact_ratio': ('rejected', 'The definition specifies a ratio for each quarantine-onset event, but the function collapses onsets to a per-step mean. In addition, missing before values become false and can qualify as onsets despite the config rule, and negative sentinels are not explicitly excluded. The supplied onset/contacts data do not trigger the latter conditions; the observation-unit mismatch remains. Not executed.'),
    'sic_meso_layer_infection_contact_ratio': ('approved', 'Fixed window=1; observed infection labels/layers and potential-contact row denominator. Zero counts are actual event counts; zero denominators are NaN. Four layer columns must be retained as separate features.'),
    'sic_macro_layer_entropy': ('approved', 'Normalized entropy of actual infection-layer counts with K from observed layers; no infection events means NaN, not zero. Actual event/contact layer domains agree in this run.'),
    'icts_meso_layer_contact_change': ('approved', 'Median of observed pre/post layer contact-count changes at strict quarantine-count increases. The generated config explicitly broadcasts this run-level, data-derived statistic. This is one independent run-level estimate, not 61 independent temporal observations; retain a constant-series warning.'),
    'icts_macro_city_contact_change_on_quarantine_increase': ('approved', 'A-B uses actual consecutive-step contact-count differences partitioned by positive versus zero quarantine-count change. Config broadcasts the data-derived run-level scalar. Record one independent estimate and constant-series warning; no causal-effect claim.'),
}
RUN_SCALARS = {'icts_meso_layer_contact_change', 'icts_macro_city_contact_change_on_quarantine_increase'}


def semantic_graph(graph):
    return {**graph, 'nodes': [{k: v for k, v in n.items() if k != 'execution'} for n in graph['nodes']]}


def generation_hashes(root):
    return {p.relative_to(root).as_posix(): digest(p) for directory in ('generation', 'indicator_code')
            for p in sorted((root / directory).rglob('*')) if p.is_file()}


def review_case(root, audit, scene):
    graph = read_json(root / 'candidate_graph.json')
    published = read_json(Path('causal_graph/examples/v2_live_20261106') / scene / 'candidate_graph.json')
    if semantic_graph(graph) != semantic_graph(published):
        raise ValueError('Original candidate definitions/relations differ from the published 30d65e1 result')
    schema = read_json(root / 'data_schema.json')
    rows, approved, rejected = [], {}, {}
    for node in graph['nodes']:
        iid = node['indicator_id']
        path = root / node['code_file']
        actual_hash = digest(path)
        if actual_hash != node['code_sha256']:
            raise ValueError(f'Original generated source changed: {iid}')
        source = path.read_text(encoding='utf-8')
        syntax = code_errors(source)
        access = analyze_access(source, node['required'], schema)
        decision, reasoning = NOTES[iid]
        if syntax or access['errors']:
            decision = 'rejected'
            reasoning = 'Syntax/field/safety structure failure: ' + str(syntax + access['errors'])
        row = {'indicator_id': iid, 'code_sha256': actual_hash, 'decision': decision,
               'mathematical_review': reasoning, 'syntax_and_basic_safety_errors': syntax,
               'field_access_review': access, 'definition_sha256': object_digest(node['mathematical_definition']),
               'config_sha256': object_digest(node['config']), 'dangerous_operations': [],
               'safety_review': 'All imports/calls and module top-level statements inspected: scientific data processing only; no file/network/process/environment access, dynamic exec/eval or random observation generation. Local subprocess timeout applies.'}
        rows.append(row)
        if decision == 'approved':
            approved[iid] = actual_hash
        else:
            rejected[iid] = {'code_sha256': actual_hash, 'reason': reasoning}
    approvals = {'reviewer': 'Codex code review explicitly authorized by the user, 2026-11-06',
                 'reviewed_at': now(), 'notes': 'Specific immutable 30d65e1 outputs reviewed against their mathematical definitions, config and original logs. See code_review_report.json. Agent-authored review, not a claimed human signature.',
                 'code_sha256': approved, 'rejections': rejected}
    audit.mkdir(parents=True, exist_ok=True)
    save_json(audit / 'code_review_report.json', {'scene': scene, 'reviewed_at': approvals['reviewed_at'],
              'semantic_graph_sha256': object_digest(semantic_graph(graph)), 'reviews': rows})
    save_json(audit / 'review.json', approvals)
    return graph, approvals


def fish_references(trajectory):
    states = trajectory.read('agent_states').query("role == 'fish'")
    contacts = trajectory.read('contacts')
    assert not states[['agent_id', 'x', 'y', 'heading']].isna().any().any()
    grouped_contacts = {int(step): g for step, g in contacts.groupby('step')}
    nearest, alignment, count, largest, local, global_ratio = {}, {}, {}, {}, {}, {}
    for step, frame in states.groupby('step', sort=True):
        step = int(step)
        ids = frame.agent_id.astype(int).to_numpy()
        points = frame[['x', 'y']].to_numpy()
        n = len(points)
        distance, _ = cKDTree(points).query(points, k=2)
        for agent, value in zip(ids, distance[:, 1]):
            nearest[(step, int(agent))] = float(value)
        centered = points - points.mean(axis=0)
        _, singular, axes = np.linalg.svd(centered, full_matrices=False)
        headings = frame.heading.to_numpy()
        projection = np.abs(np.column_stack((np.cos(headings), np.sin(headings))) @ axes[0])
        assert not np.isclose(singular[0] ** 2, singular[1] ** 2)
        for agent, value in zip(ids, projection):
            alignment[(step, int(agent))] = float(value)
        global_ratio[step] = float((singular[0] / singular[1]) ** 2)
        table = grouped_contacts.get(step)
        lookup = {int(agent): i for i, agent in enumerate(ids)}
        pairs = []
        if table is not None:
            for a, b in zip(table.agent_id, table.partner_id):
                if pd.notna(a) and pd.notna(b) and int(a) in lookup and int(b) in lookup and int(a) != int(b):
                    pairs.append((lookup[int(a)], lookup[int(b)]))
        pairs = list(set(pairs + [(b, a) for a, b in pairs]))
        adjacency = csr_matrix((np.ones(len(pairs)), tuple(np.array(pairs).T) if pairs else ([], [])), shape=(n, n))
        components, labels = connected_components(adjacency, directed=False)
        count[step] = float(components)
        largest[step] = float(np.bincount(labels).max() / n)
        ratios = []
        for i in range(n):
            neighbors = adjacency.indices[adjacency.indptr[i]:adjacency.indptr[i + 1]]
            if len(neighbors) < 2:
                continue
            covariance = np.cov(points[np.r_[i, neighbors]], rowvar=False, ddof=1)
            eigen = np.linalg.eigvalsh(covariance)
            if eigen[0] > 0:
                ratios.append(eigen[1] / eigen[0])
        local[step] = float(np.mean(ratios)) if ratios else np.nan
    return {'frag_micro_nn_distance': nearest, 'elong_micro_axis_alignment': alignment,
            'frag_meso_contact_component_count': count, 'frag_macro_largest_component_fraction': largest,
            'elong_meso_local_eigen_ratio': local, 'elong_macro_global_eigen_ratio': global_ratio}


def covasim_references(trajectory):
    events, contacts, model = (trajectory.read(t) for t in ('events', 'contacts', 'model_states'))
    assert contacts.agent_id.ge(0).all() and contacts.partner_id.ge(0).all()
    infections = events[events.event_type.eq('infection')].dropna(subset=['layer'])
    layers = sorted(set(contacts.layer.dropna()) | set(events.layer.dropna()))
    assert set(layers) == set(contacts.layer.dropna()) | set(infections.layer.dropna())
    steps = sorted(set(contacts.step) | set(infections.step))
    counts = contacts.groupby(['step', 'layer']).size().unstack(fill_value=0).reindex(index=steps, columns=layers, fill_value=0)
    incident = infections.groupby(['step', 'layer']).size().unstack(fill_value=0).reindex(index=steps, columns=layers, fill_value=0)
    ratios, entropies = {}, {}
    for step in steps:
        for layer in layers:
            denominator = counts.loc[step, layer]
            ratios[(int(step), layer)] = float(incident.loc[step, layer] / denominator) if denominator else np.nan
        values = incident.loc[step].to_numpy(dtype=float)
        entropies[int(step)] = float(entropy(values) / np.log(len(layers))) if values.sum() > 0 else np.nan
    q = model.set_index('step').quarantined.sort_index()
    onsets = q.index[q.diff().gt(0)].tolist()
    changes = []
    observed = set(contacts.step.unique())
    for t in onsets:
        pre = [s for s in range(t - 7, t) if s in observed]
        post = [s for s in range(t + 1, t + 8) if s in observed]
        if pre and post:
            changes.append(counts.loc[post].mean() - counts.loc[pre].mean())
    # This definition explicitly uses CONTACT layers, unlike the infection-label
    # union used by the entropy/ratio definitions. Seed labels are not contact layers.
    contact_layers = sorted(contacts.layer.dropna().unique())
    medians = pd.DataFrame(changes).median() if changes else pd.Series(np.nan, index=contact_layers)
    layer_change = {(int(step), layer): float(medians[layer]) for step in q.index for layer in contact_layers}
    total = contacts.groupby('step').size().sort_index()
    transitions = pd.concat([total.diff().rename('dc'), q.diff().rename('dq')], axis=1).dropna()
    increase = transitions.loc[transitions.dq.gt(0), 'dc']
    stable = transitions.loc[transitions.dq.eq(0), 'dc']
    scalar = float(increase.mean() - stable.mean()) if len(increase) and len(stable) else np.nan
    return {'sic_meso_layer_infection_contact_ratio': ratios, 'sic_macro_layer_entropy': entropies,
            'icts_meso_layer_contact_change': layer_change,
            'icts_macro_city_contact_change_on_quarantine_increase': {int(step): scalar for step in q.index}}


def compare_values(series, expected, iid):
    values = {}
    for row in series.itertuples(index=False):
        key = int(row.step)
        if hasattr(row, 'entity_id'):
            key = (key, int(json.loads(row.entity_id)['agent_id']))
        elif row.feature != 'value':
            key = (key, row.feature)
        values[key] = row.value
    if set(values) != set(expected):
        raise AssertionError(f'{iid}: output coordinates differ from mathematical reference')
    keys = sorted(values)
    actual = np.asarray([values[k] for k in keys], dtype=float)
    reference = np.asarray([expected[k] for k in keys], dtype=float)
    np.testing.assert_allclose(actual, reference, equal_nan=True, rtol=1e-7, atol=1e-9)
    mask = np.isfinite(actual) & np.isfinite(reference)
    return {'valid': True, 'reference': 'independent calculation from original Trajectory records; not substituted output',
            'coordinates_checked': len(keys), 'finite_values_checked': int(mask.sum()),
            'max_absolute_error': float(np.max(np.abs(actual[mask] - reference[mask]))) if mask.any() else None,
            'rtol': 1e-7, 'atol': 1e-9}


def main(argv=None):
    import yaml
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('causal_graph/results/v2_live_20261106'))
    parser.add_argument('--audit-root', type=Path, required=True)
    args = parser.parse_args(argv)
    root, audit_root = args.root.resolve(), args.audit_root.resolve()
    audit_root.mkdir(parents=True, exist_ok=False)
    llm = load_llm(root / 'llm.yaml')  # No API key read, no model request.
    original_settings = yaml.safe_load((root / 'pipeline.yaml').read_text(encoding='utf-8'))
    original_settings.update(execution_mode='trusted_reviewed', indicator_timeout=180)
    settings_file = audit_root / 'pipeline_local.yaml'
    settings_file.write_text(yaml.safe_dump(original_settings, sort_keys=False), encoding='utf-8')
    settings = load_pipeline(settings_file)
    summary = {'started_at': now(), 'mode': 'reviewed_local_execution_only', 'llm_requests': 0, 'scenes': []}
    for scene in ('fish', 'covasim'):
        experiment, audit = root / scene, audit_root / scene
        graph, approvals = review_case(experiment, audit, scene)
        before = generation_hashes(experiment)
        inputs = read_json(experiment / 'inputs.json')
        paths = [Path(r['directory']) for r in inputs]
        run_pipeline(paths, llm, settings, experiment, resume=True, execute_only=True, approvals=approvals)
        assert generation_hashes(experiment) == before, 'Original generation/code files changed'
        assert semantic_graph(read_json(experiment / 'candidate_graph.json')) == semantic_graph(graph)
        trajectory = Trajectory(paths[0])
        references = fish_references(trajectory) if scene == 'fish' else covasim_references(trajectory)
        reports = read_json(experiment / 'execution_report.json')
        math_report = {}
        for report in reports:
            iid = report['indicator_id']
            if report['status'] != 'success':
                continue
            actual = pd.read_parquet(experiment / report['series_file'])
            try:
                result = compare_values(actual, references[iid], iid)
            except (AssertionError, ValueError) as exc:
                result = {'valid': False, 'error': str(exc)}
                report.update(status='failed', error_type='mathematical_validation_error', error=str(exc))
            if iid in RUN_SCALARS:
                result.update(quantity_scope='run_level_scalar_broadcast', independent_estimates_per_feature=1,
                              warning='Repeated rows are the same data-derived run-level estimate, not independent temporal observations.')
            report['mathematical_validation'] = result
            math_report[iid] = result
        save_json(audit / 'mathematical_validation.json', math_report)
        save_json(experiment / 'mathematical_validation.json', math_report)
        save_json(experiment / 'execution_report.json', reports)
        export_graphs(read_json(experiment / 'candidate_graph.json'), reports, [r['manifest']['run_id'] for r in inputs], experiment)
        assert_unchanged(inputs)
        pipeline = read_json(experiment / 'pipeline_report.json')
        pipeline.update(status='completed' if all(r['status'] == 'success' for r in reports) else 'completed_with_failures',
                        successful_calculations=sum(r['status'] == 'success' for r in reports),
                        executable_nodes=len(read_json(experiment / 'executable_graph.json')['nodes']),
                        mathematical_validation_file='mathematical_validation.json')
        save_json(experiment / 'pipeline_report.json', pipeline)
        metadata = read_json(experiment / 'experiment.json')
        metadata['status'] = pipeline['status']
        invocation = experiment / metadata['invocations'][-1]
        # Retain the pre-reference execution report as separate evidence.
        original_execution = read_json(invocation / 'execution_report.json')
        save_json(invocation / 'numeric_execution_report.json', original_execution)
        save_json(invocation / 'execution_report.json', reports)
        save_json(invocation / 'pipeline_report.json', pipeline)
        save_json(experiment / 'experiment.json', metadata)
        row = {'scene': scene, 'approved': len(approvals['code_sha256']), 'review_rejected': len(approvals['rejections']),
               'success': sum(r['status'] == 'success' for r in reports),
               'failed': sum(r['status'] == 'failed' for r in reports),
               'compute_failed': sum(r['status'] == 'failed' and r.get('execution_started', False) for r in reports),
               'failures': [{'indicator_id': r['indicator_id'], 'error_type': r.get('error_type'), 'error': r.get('error')} for r in reports if r['status'] == 'failed'],
               'original_generation_hashes': before, 'generation_unchanged': True,
               'candidate_nodes': len(graph['nodes']), 'candidate_edges': len(graph['edges']),
               'executable_nodes': len(read_json(experiment / 'executable_graph.json')['nodes']),
               'executable_edges': len(read_json(experiment / 'executable_graph.json')['edges']),
               'mathematical_validation': math_report, 'output': str(experiment)}
        summary['scenes'].append(row)
        save_json(audit_root / 'acceptance_summary.json', summary)
        save_json(experiment / 'artifact_hashes.json', {p.relative_to(experiment).as_posix(): digest(p) for p in sorted(experiment.rglob('*'))
                  if p.is_file() and p.name not in {'.pipeline.lock', 'artifact_hashes.json'} and p.suffix != '.tmp'})
    summary['ended_at'] = now()
    save_json(audit_root / 'acceptance_summary.json', summary)
    print(audit_root / 'acceptance_summary.json')


if __name__ == '__main__':
    main()
