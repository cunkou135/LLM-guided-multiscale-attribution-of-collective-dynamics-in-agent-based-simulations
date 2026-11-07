"""Read-only verification of published real generation, without API calls/execution."""
import hashlib
import json
from pathlib import Path
import zipfile

import networkx as nx
from causal_graph.schemas import parse_response


def verify(directory):
    directory = Path(directory)
    hashes = json.loads((directory / 'archive_sha256.json').read_text(encoding='utf-8'))
    for filename, expected in hashes.items():
        path = directory / filename
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, filename
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            if filename.startswith('preliminary'):
                print(filename, 'checksum verified; failed preliminary runs retained')
                continue
            load = lambda name: json.loads(archive.read(name))
            for name, sha in load('artifact_hashes.json').items():
                assert hashlib.sha256(archive.read(name)).hexdigest() == sha, name
            graph = load('candidate_graph.json')
            definitions = {n['indicator_id']: n for n in load('generation/indicators/parsed.json')['indicators']}
            for node in graph['nodes']:
                assert all(node[k] == v for k, v in definitions[node['indicator_id']].items())
                raw = parse_response(archive.read(node['generation_call'] + '/response.txt').decode('utf-8'))
                code = next(c for c in raw['codes'] if c['indicator_id'] == node['indicator_id'])
                assert node['python_code'] == code['python_code']
                if node['code_file']:
                    source = archive.read(node['code_file'])
                    assert hashlib.sha256(source).hexdigest() == node['code_sha256']
                    assert source.decode('utf-8').replace('\r\n', '\n') == node['python_code']
            for edge in graph['edges']:
                for origin in edge['generation_sources']:
                    raw = parse_response(archive.read(origin['call'] + '/response.txt').decode('utf-8'))
                    item = raw['edges'][origin['row_index']]
                    assert item['edge_id'] == origin['original_edge_id']
                    assert all(edge[k] == item[k] for k in item if k != 'edge_id')
            network = nx.read_graphml(archive.open('candidate_graph.graphml'))
            assert set(network) == {n['indicator_id'] for n in graph['nodes']}
            assert set(network.edges) == {(e['source'], e['target']) for e in graph['edges']}
            assert not load('executable_graph.json')['nodes']
            assert not any(r['status'] == 'success' for r in load('execution_report.json'))
            print(filename, len(graph['nodes']), 'original variables;', len(graph['edges']), 'original candidate edges verified')


if __name__ == '__main__':
    verify(Path(__file__).resolve().parent)
