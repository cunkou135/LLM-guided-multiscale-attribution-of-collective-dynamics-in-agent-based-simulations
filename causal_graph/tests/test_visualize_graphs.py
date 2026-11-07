from pathlib import Path
import xml.etree.ElementTree as ET

from causal_graph.graph_export import assemble_graph, export_graphs
from causal_graph.io import digest, read_json, save_json
from causal_graph.visualize_graphs import export_visualizations
from .fixtures import fixture_context


def test_graph_exports_preserve_nodes_edges_and_inputs(tmp_path):
    experiment = tmp_path / 'experiment'; experiment.mkdir()
    graph = assemble_graph(fixture_context(), 'fixture_only', experiment)
    reports = [{'run_id': 'r', 'indicator_id': n['indicator_id'], 'status': 'success' if i else 'failed'} for i, n in enumerate(graph['nodes'])]
    export_graphs(graph, reports, ['r'], experiment)
    save_json(experiment / 'experiment.json', {'model_name': 'fixture'})
    before = {name: digest(experiment / name) for name in ('candidate_graph.json', 'executable_graph.json')}
    out = export_visualizations([experiment], tmp_path / 'visuals')
    manifest = read_json(out / 'visualization_manifest.json')
    assert len(manifest['views']) == 6  # candidate, executable, 3 directions, per-run
    for view in manifest['views']:
        assert digest(view['source_graph']) == view['source_graph_sha256']
        tree = ET.parse(out / (view['file'] + '.svg'))
        ids = [node.attrib['id'] for node in tree.iter() if 'id' in node.attrib]
        assert sum(i.startswith('node_') for i in ids) == view['nodes']
        assert sum(i.startswith('edge_') for i in ids) == view['edges']
        assert (out / (view['file'] + '.png')).is_file()
    assert '<svg' in (out / 'index.html').read_text(encoding='utf-8')
    assert (out / 'overview.png').is_file()
    assert before == {name: digest(experiment / name) for name in before}


def test_graphviz_exports_readable_fonts_and_routed_original_edges(tmp_path):
    import shutil
    import pytest
    from causal_graph.visualize_graphs import render_graph
    if not shutil.which('dot'):
        pytest.skip('Optional native Graphviz is absent')
    graph = assemble_graph(fixture_context(), 'fixture_only', tmp_path)
    path = tmp_path / 'routed'
    assert render_graph(graph, graph, path, 'Fixture', 'graphviz') == 'graphviz_dot'
    dot = path.with_suffix('.dot').read_text(encoding='utf-8')
    assert 'fontsize=14' in dot and 'splines=spline' in dot and 'nodesep=0.15' in dot
    assert dot.count(' -> ') == len(graph['edges'])
    assert path.with_suffix('.pdf').is_file()
    root = ET.parse(path.with_suffix('.svg')).getroot()
    assert all(root.find(f".//*[@id='node_{n['indicator_id']}']/{{http://www.w3.org/2000/svg}}title") is not None
               for n in graph['nodes'])


def test_matrix_keeps_every_directed_edge_and_variable(tmp_path):
    from causal_graph.visualize_graphs import render_matrix
    graph = assemble_graph(fixture_context(), 'fixture_only', tmp_path)
    before = repr(graph)
    path = tmp_path / 'matrix'
    render_matrix(graph, path, 'Test-only adjacency')
    tree = ET.parse(path.with_suffix('.svg'))
    elements = [n for n in tree.iter() if 'id' in n.attrib]
    assert {n.attrib['id'] for n in elements if n.attrib['id'].startswith('edge_')} == {
        'edge_' + e['edge_id'] for e in graph['edges']}
    assert {n.attrib['id'] for n in elements if n.attrib['id'].startswith('node_')} == {
        'node_' + n['indicator_id'] for n in graph['nodes']}
    assert repr(graph) == before
