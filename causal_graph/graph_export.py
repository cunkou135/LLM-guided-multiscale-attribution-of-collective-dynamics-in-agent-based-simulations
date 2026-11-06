"""Step 9: preserve complete hypotheses and induced executable subgraphs."""
from copy import deepcopy
from pathlib import Path

import networkx as nx
from jsonschema import Draft202012Validator

from .io import digest, save_json
from .schemas import GRAPH_SCHEMA, EXECUTABLE_SCHEMA


def assemble_graph(context, code_call, root):
    codes = {v['indicator_id']: v for v in context['codes']}
    folder = Path(root) / 'indicator_code'
    folder.mkdir(exist_ok=True)
    nodes = []
    for definition in context['indicators']:
        code = codes[definition['indicator_id']]
        file = folder / f'{definition["indicator_id"]}.py'
        if file.exists() and file.read_text(encoding='utf-8') != code['python_code']:
            raise ValueError(f'Generated code modified outside generation: {file.name}; retain original and use a separate human revision record')
        file.write_text(code['python_code'], encoding='utf-8')
        nodes.append({**definition, **{k: v for k, v in code.items() if k != 'indicator_id'},
                      'node_id': definition['indicator_id'], 'code_file': file.relative_to(root).as_posix(),
                      'code_sha256': digest(file), 'generation_call': code_call})
    graph = {'schema_version': '1.0', 'evidence_status': 'unvalidated_semantic_candidates',
             'phenomena': deepcopy(context['phenomena']), 'nodes': nodes, 'edges': deepcopy(context['edges'])}
    Draft202012Validator(GRAPH_SCHEMA).validate(graph)
    return graph


def export_graphml(graph, path):
    network = nx.DiGraph(evidence_status=graph['evidence_status'], schema_version='1.0')
    for node in graph['nodes']:
        network.add_node(node['indicator_id'], **{k: node[k] for k in
                         ('name', 'scale', 'phenomenon_id', 'description', 'mathematical_definition', 'units')})
    for edge in graph['edges']:
        network.add_edge(edge['source'], edge['target'], **{k: edge[k] for k in ('edge_id', 'semantic_rationale', 'relation_type')})
    nx.write_graphml(network, path, encoding='utf-8')


def executable_subgraph(graph, reports, run_ids):
    statuses = {(r['run_id'], r['indicator_id']): r['status'] for r in reports}
    successful = {n['indicator_id'] for n in graph['nodes'] if
                  all(statuses.get((rid, n['indicator_id'])) == 'success' for rid in run_ids)}
    result = {**graph, 'nodes': [deepcopy(n) for n in graph['nodes'] if n['indicator_id'] in successful],
              'edges': [deepcopy(e) for e in graph['edges'] if e['source'] in successful and e['target'] in successful]}
    result['run_ids'] = run_ids
    result['execution_policy'] = 'success_on_every_listed_run'
    result['excluded_nodes'] = [{'indicator_id': n['indicator_id'], 'run_status': {
        rid: statuses.get((rid, n['indicator_id']), 'not_executed') for rid in run_ids}}
        for n in graph['nodes'] if n['indicator_id'] not in successful]
    result['excluded_edges'] = [{'edge': deepcopy(e), 'reason': 'source_or_target_not_successful_on_every_run'}
                               for e in graph['edges'] if e not in result['edges']]
    # Paths may be broken by execution failures; they are reported, never filled in.
    pairs = {(e['source'], e['target']) for e in result['edges']}
    scale = {n['indicator_id']: n['scale'] for n in result['nodes']}
    covered = set()
    for s, m in pairs:
        if scale[s] == 'micro':
            for other, t in pairs:
                if other == m and scale[t] == 'macro':
                    covered.update((s, m, t))
    result['nodes_without_complete_path'] = sorted(successful - covered)
    Draft202012Validator(EXECUTABLE_SCHEMA).validate(result)
    return result


def export_graphs(graph, reports, run_ids, root):
    root = Path(root)
    save_json(root / 'candidate_graph.json', graph)
    export_graphml(graph, root / 'candidate_graph.graphml')
    executable = executable_subgraph(graph, reports, run_ids)
    save_json(root / 'executable_graph.json', executable)
    export_graphml(executable, root / 'executable_graph.graphml')
    for rid in run_ids:
        folder = root / 'per_run' / rid
        folder.mkdir(parents=True, exist_ok=True)
        subgraph = executable_subgraph(graph, reports, [rid])
        save_json(folder / 'executable_graph.json', subgraph)
        export_graphml(subgraph, folder / 'executable_graph.graphml')
    return executable
