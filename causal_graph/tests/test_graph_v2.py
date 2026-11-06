from copy import deepcopy

import networkx as nx
import pytest

from causal_graph.graph_export import merge_candidate_edges, assemble_graph, export_graphs
from causal_graph.schemas import validate_stage
from .fixtures import fixture_context


def test_bidirectional_feedback_direct_links_isolates_and_dedup(tmp_path, settings):
    ctx = fixture_context()
    extra = {**ctx['indicators'][0], 'indicator_id': 'test_d', 'name': 'isolated micro'}
    ctx['indicators'].append(extra)
    ctx['codes'].append({**ctx['codes'][0], 'indicator_id': 'test_d'})
    up = ctx['edges_upward'][0]
    ctx['edges_upward'].append({**up, 'edge_id': 'same_endpoints_again'})
    ctx['edges_upward'].append({**up, 'edge_id': 'direct_ac', 'source': 'test_a', 'target': 'test_c'})
    calls = {s: f'actual_call/{s}' for s in ('edges_upward', 'edges_downward', 'edges_intrascale')}
    edges, report = merge_candidate_edges(ctx, calls, settings)
    assert len(report['duplicates']) == 1
    assert len(next(e for e in edges if e['source'] == 'test_a' and e['target'] == 'test_b')['generation_sources']) == 2
    ctx['merged_edges'] = edges
    graph = assemble_graph(ctx, 'actual_code_call', tmp_path)
    reports = [{'run_id': 'r', 'indicator_id': n['indicator_id'], 'status': 'success'} for n in graph['nodes']]
    executable = export_graphs(graph, reports, ['r'], tmp_path)
    network = nx.read_graphml(tmp_path / 'candidate_graph.graphml')
    assert network.has_edge('test_a', 'test_c') and network.has_edge('test_c', 'test_a')
    assert not nx.is_directed_acyclic_graph(network)
    assert 'test_d' in network and network.degree('test_d') == 0
    assert len(executable['nodes']) == 4


def test_cross_phenomenon_and_intrascale_cycle(settings):
    ctx = fixture_context()
    other = {**ctx['indicators'][0], 'indicator_id': 'test_other', 'phenomenon_id': 'other', 'name': 'other micro'}
    ctx['indicators'].append(other)
    base = {**ctx['edges_upward'][0], 'scale_direction': 'intra_scale'}
    value = {'edges': [{**base, 'edge_id': 'one', 'source': 'test_a', 'target': 'test_other'},
                       {**base, 'edge_id': 'two', 'source': 'test_other', 'target': 'test_a'}]}
    assert validate_stage('edges_intrascale', value, ctx, settings)['valid']


@pytest.mark.parametrize('stage,source,target', [('edges_upward', 'test_a', 'test_c'),
                                              ('edges_downward', 'test_c', 'test_a')])
def test_all_scale_distances_allowed(settings, stage, source, target):
    ctx = fixture_context()
    edge = {**ctx[stage][0], 'source': source, 'target': target}
    assert validate_stage(stage, {'edges': [edge]}, ctx, settings)['valid']


def test_empty_edges_valid_and_no_self_loops(settings):
    ctx = fixture_context()
    for stage in ('edges_upward', 'edges_downward', 'edges_intrascale'):
        assert validate_stage(stage, {'edges': []}, ctx, settings)['valid']
    edge = {**ctx['edges_upward'][0], 'source': 'test_a', 'target': 'test_a', 'scale_direction': 'intra_scale'}
    assert not validate_stage('edges_intrascale', {'edges': [edge]}, ctx, settings)['valid']
