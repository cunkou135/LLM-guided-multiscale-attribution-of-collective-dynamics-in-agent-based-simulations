"""Step 9: preserve complete hypotheses and induced executable subgraphs."""
from copy import deepcopy
from pathlib import Path

import networkx as nx
from jsonschema import Draft202012Validator

from .io import digest, save_json
from .schemas import GRAPH_SCHEMA, EXECUTABLE_SCHEMA


def merge_candidate_edges(context, calls, limits):
    from .schemas import EDGE_STAGES, validate_stage
    merged, lookup, duplicates = [], {}, []
    nodes={n['indicator_id']:n for n in context['indicators']}
    for stage in EDGE_STAGES:
        raw=context[stage]
        report=validate_stage(stage,{'edges':raw},context,limits)
        if not report['valid']:raise ValueError(f'{stage}: {report["errors"]}')
        for index, edge in enumerate(raw):
            provenance={'stage':stage,'call':calls[stage],'original_edge_id':edge['edge_id'],'row_index':index}
            pair=(edge['source'],edge['target'])
            if pair in lookup:
                existing=lookup[pair]
                existing['generation_sources'].append(provenance)
                duplicates.append({'retained_edge_id':existing['edge_id'],'duplicate_source':provenance})
                continue
            item={**deepcopy(edge),'edge_id':f'{edge["scale_direction"]}__{edge["edge_id"]}',
                  'source_phenomenon':nodes[edge['source']]['phenomenon_id'],
                  'target_phenomenon':nodes[edge['target']]['phenomenon_id'],
                  'generation_sources':[provenance]}
            lookup[pair]=item
            merged.append(item)
    if len(merged)>limits.max_edges:raise ValueError('Merged graph exceeds max_edges')
    return merged,{'raw_edges':sum(len(context[s]) for s in EDGE_STAGES),'retained_edges':len(merged),'duplicates':duplicates}


def assemble_graph(context, code_call, root):
    codes={v['indicator_id']:v for v in context['codes']}
    folder=Path(root)/'indicator_code'
    folder.mkdir(exist_ok=True)
    nodes=[]
    for definition in context['indicators']:
        code=codes[definition['indicator_id']]
        file=None
        if code['implementation_status']=='implemented':
            file=folder/f'{definition["indicator_id"]}.py'
            if file.exists() and file.read_text(encoding='utf-8')!=code['python_code']:
                raise ValueError(f'Generated code modified outside generation: {file.name}')
            if not file.exists():
                file.write_text(code['python_code'],encoding='utf-8')
        nodes.append({**definition,**{k:v for k,v in code.items() if k!='indicator_id'},
                      'node_id':definition['indicator_id'],'code_file':file.relative_to(root).as_posix() if file else None,
                      'code_sha256':digest(file) if file else None,'generation_call':code_call,'execution':{}})
    graph={'schema_version':'2.0','evidence_status':'unvalidated_semantic_candidates',
           'phenomena':deepcopy(context['phenomena']),'nodes':nodes,'edges':deepcopy(context['merged_edges'])}
    Draft202012Validator(GRAPH_SCHEMA).validate(graph)
    return graph


def export_graphml(graph, path):
    network = nx.DiGraph(evidence_status=graph['evidence_status'], schema_version=graph['schema_version'])
    for node in graph['nodes']:
        network.add_node(node['indicator_id'], **{k: node[k] for k in
                         ('name', 'scale', 'phenomenon_id', 'description', 'mathematical_definition', 'units')})
    for edge in graph['edges']:
        network.add_edge(edge['source'], edge['target'], **{k: edge[k] for k in ('edge_id', 'scale_direction', 'semantic_rationale', 'relation_type', 'source_phenomenon', 'target_phenomenon')})
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
    Draft202012Validator(EXECUTABLE_SCHEMA).validate(result)
    return result


def export_graphs(graph, reports, run_ids, root):
    root = Path(root)
    for node in graph['nodes']:
        node['execution']={r['run_id']:{k:r[k] for k in ('status','error_type','error','reason','series_file','series_sha256') if k in r}
                           for r in reports if r['indicator_id']==node['indicator_id']}
    Draft202012Validator(GRAPH_SCHEMA).validate(graph)
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
