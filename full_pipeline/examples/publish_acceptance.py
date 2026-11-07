"""Verify and archive actual live acceptance; exclude raw simulations and all private credentials."""
from pathlib import Path
from shutil import copyfile
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from causal_graph.io import digest, read_json, save_json
from full_pipeline.main import filesystem_path
from full_pipeline.validators import definition_hash, validate_stage1, validate_stage2
from causal_discovery.m5_graph import integrate_graph


def main():
    published = ROOT / 'full_pipeline/examples/acceptance_20261107'; published.mkdir(parents=True, exist_ok=True)
    summary = []
    for scene in ('fish', 'covasim'):
        experiment = filesystem_path(ROOT / f'full_pipeline/results/live_{scene}_20261107')
        report = read_json(experiment / 'pipeline_report.json'); assert report['status'] == 'completed'
        stage1, final = (read_json(experiment / name) for name in ('stage1_graph.json', 'final_causal_graph.json'))
        validate_stage1(stage1)
        audit = Path(final['provenance']['audit_directory'])
        validate_stage2(final, stage1, audit)
        replay = integrate_graph(stage1, read_json(audit / 'm1_data.json'), read_json(audit / 'm2_lag_results.json'),
                                 read_json(audit / 'm3_granger_results.json'), read_json(audit / 'm4_pid_results.json'), read_json(audit / 'parameters.json'))['graph']
        assert replay['nodes'] == final['nodes'] and replay['edges'] == final['edges']
        review = read_json(experiment / 'internal/stage1/review.json')
        for node in stage1['nodes']:
            checked = review['reviews'][node['node_id']]
            assert checked['verdict'] == 'approved' and checked['definition_sha256'] == definition_hash(node)
            assert checked['code_sha256'] == node['code_sha256'] == digest(node['code_file'])
        model_files = list(audit.rglob('*.pt'))
        for record in read_json(audit / 'm2_lag_results.json'):
            for card in record.get('models', []):
                assert digest(card['parameter_file']) == card['parameter_sha256']
        for file in model_files:
            saved = torch.load(file, map_location='cpu', weights_only=True)
            assert all(torch.isfinite(v).all() for v in saved['state_dict'].values())
            assert sum(v.numel() for v in saved['state_dict'].values()) == saved['model_card']['parameter_count']
        numerical = read_json(experiment / 'internal/validation/independent_numeric_checks.json')
        assert numerical['status'] == 'passed' and numerical['source_graph_sha256'] == digest(experiment / 'stage1_graph.json')
        out = published / scene; out.mkdir(exist_ok=True)
        for name in ('stage1_graph.json', 'final_causal_graph.json', 'pipeline_report.json'):
            copyfile(experiment / name, out / name)
        copyfile(experiment / 'input/scenario.md', out / 'scenario.md')
        copyfile(experiment / 'internal/validation/independent_numeric_checks.json', out / 'independent_numeric_checks.json')
        # Keep the full attempt journal, generated source, actual indicator observations
        # and NN weights. Original simulation Parquet stays in its existing run folder.
        archive = out / 'internal_audit.zip'
        with ZipFile(archive, 'w', ZIP_DEFLATED, compresslevel=6) as bundle:
            for file in sorted((experiment / 'internal').rglob('*')):
                if file.is_file() and not file.is_relative_to(experiment / 'internal/simulation'):
                    bundle.write(file, file.relative_to(experiment).as_posix())
        with ZipFile(archive) as bundle: assert bundle.testzip() is None
        execution = read_json(experiment / 'internal/stage1/latest_execution.json')['execution_reports']
        row = {k: report[k] for k in ('raw_candidate_nodes', 'raw_candidate_edges', 'stage1_nodes', 'stage1_edges',
            'actual_valid_nodes', 'final_nodes', 'final_edges', 'llm_generation_calls', 'http_attempts', 'retry_attempts', 'seeds', 'total_active_seconds')}
        row.update(scene=scene, successful_executions=sum(r['status'] == 'success' for r in execution),
                   total_executions=len(execution), actual_models=len(model_files), numerical_spot_checks=len(numerical['checks']),
                   numerical_values_compared=numerical['compared_values'], external_accepted_edges=sum(e['source'] != e['target'] for e in final['edges']),
                   final_weights=[{'source': e['source'], 'target': e['target'], 'weight': e['weight'], 'relation_type': e['relation_type']} for e in final['edges']],
                   excluded_from_analysis={iid: value['reason'] for iid, value in report['invalid_nodes'].items()})
        summary.append(row)
    copyfile(ROOT / 'full_pipeline/results/full_regression.xml', published / 'full_regression.xml')
    save_json(published / 'verification.json', {'status': 'verified', 'experiments': summary,
        'full_pipeline_sources': {p.name: digest(p) for p in (ROOT / 'full_pipeline').glob('*.py')},
        'boundary': 'Actual LLM and simulation results; no structural causal truth claim. Raw simulation Parquet is retained locally, not duplicated in this archive.'})
    files = sorted(p for p in published.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
    (published / 'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.relative_to(published).as_posix()}\n' for p in files), encoding='utf-8')
    print([(r['scene'], r['stage1_nodes'], r['stage1_edges'], r['final_nodes'], r['final_edges'], r['llm_generation_calls']) for r in summary])


if __name__ == '__main__': main()
