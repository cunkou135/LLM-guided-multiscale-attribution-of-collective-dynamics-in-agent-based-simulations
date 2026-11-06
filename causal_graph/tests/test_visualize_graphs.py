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
