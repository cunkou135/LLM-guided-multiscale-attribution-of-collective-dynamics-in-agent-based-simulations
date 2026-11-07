"""Check saved numerical evidence, source preservation, graph integrity and actual GRU weights."""
import argparse
from collections import Counter
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from causal_discovery._common import read_json, save_json, sha256
from causal_discovery.m5_graph import validate_final_graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'causal_discovery/results/acceptance_20261107')
    parser.add_argument('--junit', type=Path, default=ROOT / 'causal_discovery/results/full_regression.xml')
    args = parser.parse_args(); folder = args.input.resolve()
    commands = read_json(folder / 'commands.json')
    assert len(commands) >= 14 and all(c['exit_code'] == 0 for c in commands)
    final = read_json(folder / 'demo_final_causal_graph.json'); validate_final_graph(final)
    source = read_json(folder / 'demo_input_graph.json')
    original = {n['node_id']: n for n in source['nodes']}
    for node in final['nodes']:
        assert all(node[k] == v for k, v in original[node['node_id']].items())
    audit = folder / 'demo_final_causal_graph_audit'
    lags = {r['target']: r for r in read_json(audit / 'm2_lag_results.json')}
    originals = {e['edge_id']: e for e in source['edges']}
    for edge in final['edges']:
        if edge['source'] == edge['target']:
            assert edge['weight'] == lags[edge['target']]['primary_self_lag']
        else:
            assert edge['weight'] == lags[edge['target']]['primary_lags'][edge['source']]
            prior = originals[edge['edge_id']]
            for key in ('source', 'target', 'scale_direction', 'semantic_rationale'):
                assert edge[key] == prior[key]
        for evidence in edge['evidence']:
            if evidence['kind'] == 'pid_joint':
                assert evidence['joint_calibration']['p_value_valid'] and evidence['synergy_calibration']['p_value_valid']
                assert evidence['joint_adjusted_p_value'] <= .05 and evidence['synergy_adjusted_p_value'] <= .05
            else:
                assert evidence['calibration']['p_value_valid'] and evidence['adjusted_p_value'] <= .05
    assert {n['node_id'] for n in final['nodes']} == {'X', 'A', 'B', 'Y', 'Z', 'W'}
    assert not any('bad' in (e['source'], e['target']) or 'W' in (e['source'], e['target']) for e in final['edges'])
    models = list(folder.rglob('*.pt')); model_hashes = {sha256(p): p for p in models}
    referenced = []
    for file in folder.rglob('*.json'):
        payload = read_json(file)
        def inspect(value):
            if isinstance(value, dict):
                if 'parameter_sha256' in value:
                    assert value['parameter_sha256'] in model_hashes
                    referenced.append(value['parameter_sha256'])
                for item in value.values(): inspect(item)
            elif isinstance(value, list):
                for item in value: inspect(item)
        inspect(payload)
    for file in models:
        model = torch.load(file, map_location='cpu', weights_only=True)
        assert sum(t.numel() for t in model['state_dict'].values()) == model['model_card']['parameter_count']
        assert all(torch.isfinite(t).all() for t in model['state_dict'].values())
    data_checks = []
    for scene in ('fish', 'covasim', 'rich_fish', 'rich_covasim'):
        path = folder / scene / 'final_causal_graph.json'
        if not path.exists(): continue
        graph = read_json(path); validate_final_graph(graph)
        report = read_json(path.parent / 'final_causal_graph_audit/pipeline_report.json')
        assert report['new_llm_calls'] == 0 and report['status'] == 'no_analyzable_nodes'
        assert not graph['nodes'] and not graph['edges']
        data = read_json(path.parent / 'final_causal_graph_audit/m1_data.json')
        assert sha256(data['source_graph']) == data['source_sha256']
        for node in data['data_report'].values():
            for item in node['source_files'].values():
                assert sha256(item['path']) == item['sha256']
                data_checks.append({'path': item['path'], 'sha256': item['sha256']})
    for filename, digest in final['provenance']['source_modules_sha256'].items():
        assert sha256(ROOT / 'causal_discovery' / filename) == digest
    suite = ET.parse(args.junit).getroot().find('testsuite')
    assert suite is not None and suite.attrib['failures'] == suite.attrib['errors'] == suite.attrib['skipped'] == '0'
    counts = Counter(case.attrib['classname'].rsplit('.', 1)[-1] for case in suite.findall('testcase'))
    result = {'status': 'verified', 'cli_commands': len(commands), 'tests': int(suite.attrib['tests']),
              'test_file_counts': counts, 'demo_nodes': len(final['nodes']), 'demo_edges': len(final['edges']),
              'edges': [{k: e[k] for k in ('edge_id', 'source', 'target', 'weight', 'relation_type')} for e in final['edges']],
              'actual_parameter_files': len(models), 'model_hash_references_checked': len(referenced),
              'original_observation_files_unchanged': data_checks,
              'checks': ['schema and complete joint groups', 'original node definitions and external IDs preserved',
                         'weights equal estimated M2 primary lags', 'accepted numerical evidence passes correction',
                         'invalid node and incident edges absent', 'valid independent isolate retained',
                         'actual tensor weights finite, counts and SHA-256 verified', 'source graph and observations unchanged',
                         'saved algorithm hashes match current Python sources', 'all regression tests passed without skips']}
    save_json(folder / 'verification.json', result)
    print(f'Verified {result["tests"]} tests, {len(models)} parameter files, {len(final["nodes"])} nodes and {len(final["edges"])} edges')


if __name__ == '__main__': main()
