"""Scenario → existing stage-one functions → existing causal_discovery pipeline."""
import argparse
from copy import deepcopy
from dataclasses import replace
import json
import os
import re
from pathlib import Path
import shutil
import time
import traceback
import uuid

import yaml

from causal_graph import generation
from causal_graph.config import load_llm, load_pipeline
from causal_graph.data_schema import build_data_schema
from causal_graph.graph_export import assemble_graph, export_graphs, merge_candidate_edges
from causal_graph.indicator_runner import execute_indicator
from causal_graph.inputs import assert_unchanged, inspect_runs
from causal_graph.io import digest, now, object_digest, read_json, save_json
from causal_graph.llm_client import LLMClient
from causal_discovery._common import settings as discovery_settings
from causal_discovery.m1_data import adapt_graph
from causal_discovery.pipeline import run_pipeline as discover
from .scenario_adapter import ROOT, coverage_report, match_scenario, prepare_run, simulation_config, source_identity
from .stage_manager import QualityError, StageFailure, StageManager, artifact_reference, verify_reference
from .validators import check_generation, classify_error, issue, reviewed_approvals, validate_stage1, validate_stage2
from .definition_repair import repair_definitions, restore_revisions


def load_config(path=None, overrides=None):
    cfg = yaml.safe_load(Path(__file__).with_name('config.yaml').read_text(encoding='utf-8'))
    def merge(a, b, prefix=''):
        if not isinstance(b, dict): raise ValueError(f'{prefix}: mapping required')
        if a and set(b) - set(a): raise ValueError(f'{prefix}: unknown keys {set(b) - set(a)}')
        return {**a, **{k: merge(a[k], v, prefix + k + '.') if isinstance(a.get(k), dict) else deepcopy(v) for k, v in b.items()}}
    if path: cfg = merge(cfg, yaml.safe_load(Path(path).read_text(encoding='utf-8-sig')))
    if overrides: cfg = merge(cfg, overrides)
    s, retry = cfg['simulation'], cfg['retry']
    seeds = s['seeds'] + s['additional_seeds']
    if (not s['use_registered_scenario'] or not s['seeds'] or len(seeds) != len(set(seeds)) or
            any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds)):
        raise ValueError('Distinct independent seeds and registered scenarios are required')
    if type(s['max_total_runs']) is not int or not len(s['seeds']) <= s['max_total_runs'] <= 64:
        raise ValueError('max_total_runs must include initial seeds and be <=64')
    if not isinstance(s['seeds_by_model'],dict) or set(s['seeds_by_model']) - {'fish','covasim'}:
        raise ValueError('seeds_by_model supports only registered fish/covasim')
    for selected in s['seeds_by_model'].values():
        if (not isinstance(selected,list) or not selected or len(selected)>s['max_total_runs'] or len(selected)!=len(set(selected)) or
                any(type(seed) is not int or not 0 <= seed < 2**32 for seed in selected)):
            raise ValueError('Model-specific seeds must be distinct, explicit and within the run budget')
    if type(s['sampling_frequency']) is not int or s['sampling_frequency'] < 1: raise ValueError('Invalid sampling frequency')
    if type(retry['max_attempts_per_stage']) is not int or not 1 <= retry['max_attempts_per_stage'] <= 10:
        raise ValueError('Bounded stage attempts (1–10) required')
    if any(type(retry[k]) is not bool for k in ('retry_invalid_json', 'retry_invalid_schema', 'retry_invalid_code')):
        raise ValueError('Retry switches must be booleans')
    if cfg['stage1']['execution_mode'] != 'trusted_reviewed': raise ValueError('full_pipeline uses explicitly reviewed local Python only')
    if cfg['experiment_mode'] not in ('research', 'interface_test'):
        raise ValueError('experiment_mode must be research or explicit interface_test')
    return cfg


def _sources(package):
    return {**{p.name: digest(p) for p in (ROOT / package).glob('*.py')},
            'observation_contract.py': digest(ROOT / 'observation_contract.py')}


def load_configured_credential(cfg, llm):
    """Optional explicitly configured private file; never serialize its secret."""
    if os.environ.get(llm.api_key_env): return
    private = cfg['stage1'].get('credential_file')
    local = ROOT / 'full_pipeline/config.local.yaml'
    if not private and local.exists():
        private = yaml.safe_load(local.read_text(encoding='utf-8-sig')).get('stage1', {}).get('credential_file')
    if private:
        value = read_json(ROOT / private).get('api_key')
        if not isinstance(value, str) or not value.strip(): raise ValueError('Configured private credential file has no nonempty api_key')
        os.environ[llm.api_key_env] = value


class AuditedClient:
    def __init__(self, base, root, stage, previous):
        self.base, self.root, self.stage, self.previous = base, root, stage, previous
        self.mode = base.mode

    def complete(self, messages, directory):
        messages = deepcopy(messages)
        if self.previous:
            messages.append({'role': 'user', 'content': json.dumps({
                'local_repair_only': True, 'stage': self.stage, 'validation_errors': self.previous,
                'constraints': 'Repair only this task. Preserve supplied definitions/IDs. No statistical outcomes, true edges, true lags, reference answers or intervention evidence are supplied.'}, ensure_ascii=False)})
        save_json(Path(directory).parent / 'actual_prompt.json', messages)
        file = self.root / 'internal/logs/llm_calls' / (uuid.uuid4().hex + '.json')
        record = {'stage': self.stage, 'client_mode': self.mode, 'started_at': now(), 'directory': str(directory),
                  'repair': bool(self.previous), 'status': 'running'}
        save_json(file, record)
        try:
            result = self.base.complete(messages, directory)
            record['status'] = 'success'
            return result
        except Exception as exc:
            record.update(status='failed', error=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            record['ended_at'] = now(); save_json(file, record)


def generation_inputs(stage, context, limits, client, scenario, cfg):
    _, provenance, request = generation.stage_request(stage, scenario['text'], context, limits)
    return {'stage': stage, 'context': context if stage in ('indicators', 'codes') else
              {k: v for k, v in context.items() if k in ('phenomena', 'indicators')},
              'scenario_sha256': scenario['scenario_sha256'], 'request_sha256': request, 'provenance': provenance,
              'client': client.mode, 'llm': cfg['_llm_identity']}


def generate_task(manager, stage, context, limits, client, root, scenario, cfg, *, item=None, initial=None):
    task = 'code_' + item if item else stage
    inputs = generation_inputs(stage, context, limits, client, scenario, cfg)
    def action(folder, previous):
        if initial is not None and not previous:
            verify_reference(initial['source_response'])
            save_json(folder / 'batch_candidate.json', initial)
            parsed = {'codes': [initial['code']]}
            report = check_generation(stage, parsed, context, limits)
            save_json(folder / 'quality_validation.json', report)
            return {'parsed': parsed, 'call': initial['call'], 'root': initial['root'], 'source_response': initial['source_response']}
        wrapped = AuditedClient(client, root, task, previous)
        functions = {'phenomena': generation.identify_phenomena, 'indicators': generation.define_indicators,
            'codes': generation.generate_codes, 'edges_upward': generation.propose_upward_edges,
            'edges_downward': generation.propose_downward_edges, 'edges_intrascale': generation.propose_intrascale_edges}
        try:
            parsed, call = functions[stage](scenario['text'], context, replace(limits, generation_attempts=1), wrapped, folder)
        except (ValueError, TypeError) as exc:
            errors = []
            for p in folder.rglob('validation.json'):
                errors.extend(read_json(p).get('errors', []))
            raise QualityError([issue(stage, classify_error(stage, e), e, item) for e in (errors or [str(exc)])]) from exc
        report = check_generation(stage, parsed, context, limits)
        save_json(folder / 'quality_validation.json', report)
        return {'parsed': parsed, 'call': str((folder / call).resolve()), 'root': str(folder.resolve())}
    def validate(value):
        if value.get('source_response'): verify_reference(value['source_response'])
        check_generation(stage, value['parsed'], context, limits)
    def allowed(issues):
        for problem in issues:
            kind = problem['type']
            flag = 'retry_invalid_json' if kind == 'invalid_json' else 'retry_invalid_code' if kind in (
                'invalid_code', 'code_definition_mismatch', 'indicator_execution_failure') else 'retry_invalid_schema'
            if not cfg['retry'][flag]: return False
        return True
    return manager.run(task, inputs, action, validator=validate, retry=True, retry_allowed=allowed), inputs


def initial_code_batches(manager, context, limits, client, root, scenario, cfg):
    """Batch only previously unrequested functions; each result is checked/adopted separately."""
    if limits.code_batch_size <= 1: return {}
    needed = []
    for node in context['indicators']:
        one = {'data_schema': context['data_schema'], 'phenomena': context['phenomena'], 'indicators': [node]}
        identity = generation_inputs('codes', one, limits, client, scenario, cfg)
        if not list(manager.directory('code_' + node['indicator_id'], identity).glob('attempt_*')): needed.append(node)
    candidates = {}
    for start in range(0, len(needed), limits.code_batch_size):
        nodes = needed[start:start + limits.code_batch_size]
        local = {'data_schema': context['data_schema'], 'phenomena': context['phenomena'], 'indicators': nodes}
        inputs = generation_inputs('codes', local, limits, client, scenario, cfg)
        name = 'code_batch_' + object_digest([n['indicator_id'] for n in nodes])[:16]
        def batch(folder, previous, local=local):
            wrapped = AuditedClient(client, root, name, previous)
            try:
                parsed, call = generation.generate_stage('codes', scenario['text'], local,
                    replace(limits, generation_attempts=1), wrapped, folder, allow_partial_codes=True)
            except (ValueError, TypeError) as exc:
                errors = [error for p in folder.rglob('validation.json') for error in read_json(p).get('errors', [])]
                raise QualityError([issue('codes', classify_error('codes', error), error) for error in (errors or [str(exc)])]) from exc
            return {'parsed': parsed, 'call': str((folder / call).resolve()), 'root': str(folder.resolve()),
                    'candidate_batch_only_not_code_approval': True}
        value = manager.run(name, inputs, batch, retry=True)
        for code in value['parsed']['codes']:
            candidates[code['indicator_id']] = {'code': code, 'call': value['call'], 'root': value['root'],
                'source_response': artifact_reference(Path(value['call']) / 'response.txt')}
        # Preserve every valid sibling BEFORE a malformed sibling can exhaust
        # its retry budget. Resuming must not request those successful functions.
        for node in nodes:
            iid = node['indicator_id']
            if iid not in candidates: continue
            one = {'data_schema':context['data_schema'], 'phenomena':context['phenomena'], 'indicators':[node]}
            try: check_generation('codes', {'codes':[candidates[iid]['code']]}, one, limits)
            except QualityError: continue
            generate_task(manager,'codes',one,limits,client,root,scenario,cfg,item=iid,initial=candidates[iid])
    return candidates


def publish(source: Path, destination: Path):
    if destination.exists() and digest(destination) != digest(source):
        history = destination.parent / 'internal/publication_history' / destination.stem / (digest(destination) + '.json')
        history.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(destination, history)
    save_json(destination, read_json(source))


def _report(root, status, started, **extra):
    calls = [read_json(p) for p in (root / 'internal/logs/llm_calls').glob('*.json')]
    audits = [read_json(p) for p in (root / 'internal/checkpoints').glob('*/**/attempt_*/audit.json')]
    http_attempts = {(str(p.parent), re.match(r'transport_(\d+)', p.name)[1])
                     for p in (root / 'internal/checkpoints').rglob('transport_*.json') if re.match(r'transport_(\d+)', p.name)}
    metadata_files = [p for p in (root/'internal/checkpoints').rglob('transport_*.json') if re.fullmatch(r'transport_\d+\.json',p.name)]
    responses = [read_json(p) for p in metadata_files]
    usages = [r['usage'] for r in responses if isinstance(r.get('usage'),dict)]
    elapsed = time.monotonic() - started
    prior = [read_json(p) for p in (root / 'internal/logs/invocations').glob('*.json')]
    report = {'status': status, 'updated_at': now(), 'invocation_elapsed_seconds': elapsed,
              'total_active_seconds': elapsed + sum(p['invocation_elapsed_seconds'] for p in prior),
              'llm_generation_calls': len(calls), 'llm_call_records': calls,
              'http_attempts': len(http_attempts),
              'actual_response_models': sorted({r['actual_model'] for r in responses if r.get('actual_model')}),
              'reported_token_usage': {k:sum(int(u.get(k,0) or 0) for u in usages) for k in ('prompt_tokens','completion_tokens','total_tokens')},
              'http_responses_with_token_usage':len(usages),
              'retry_attempts': sum(a['attempt'] > 1 for a in audits),
              'stage_attempts': [{k: a.get(k) for k in ('task', 'attempt', 'status', 'started_at', 'ended_at', 'issues')} for a in audits], **extra}
    metadata = read_json(root / 'internal/experiment.json')
    report.update(experiment_mode=metadata['config'].get('experiment_mode', 'legacy_interface_test'),
                  configuration_sources=metadata.get('config_sources', {}))
    for filename, prefix in [('stage1_graph.json', 'stage1'), ('final_causal_graph.json', 'final')]:
        if (root / filename).exists():
            graph = read_json(root / filename)
            report.update({prefix + '_nodes': len(graph['nodes']), prefix + '_edges': len(graph['edges']), prefix + '_sha256': digest(root / filename)})
    candidate = root / 'internal/stage1/latest_execution.json'
    if candidate.exists():
        raw = read_json(candidate)
        report.update(raw_candidate_nodes=raw['candidate_nodes'], raw_candidate_edges=raw['candidate_edges'])
    save_json(root / 'internal/logs/invocations' / (uuid.uuid4().hex + '.json'), report)
    save_json(root / 'pipeline_report.json', report)
    return report


def _run_stage1(manager, root, registered, metadata, records, runs, schema, cfg, limits, client, review_file, started, dcfg):
    approved_path = Path(review_file or cfg['stage1']['review_file'] or root / 'internal/stage1/review.json').resolve()
    stage1_identity = {'schema': object_digest(schema), 'run_hashes': [r['data_hashes'] for r in runs],
                'client_mode':client.mode,
                'llm': cfg['_llm_identity'], 'settings': limits.summary(), 'sources': _sources('causal_graph'),
                'quality': digest(Path(__file__).with_name('validators.py')),
                'review': digest(approved_path) if approved_path.exists() else None}
    ready_file = root / 'internal/checkpoints/stage1_ready.json'
    if ready_file.exists():
        saved = read_json(ready_file)
        if saved['identity'] == stage1_identity:
            for dependency in saved.get('dependencies', []): verify_reference(dependency)
            verify_reference(saved['published']); verify_reference(saved['candidate'])
            executable = read_json(saved['published']['path']); validate_stage1(executable)
            return {'graph': read_json(saved['candidate']['path']), 'executable': executable, 'reused': True}
    manager.state('stage1_generating')
    context = {'data_schema': schema}
    p, _ = generate_task(manager, 'phenomena', context, limits, client, root, registered, cfg)
    context.update(p['parsed'])
    variables, _ = generate_task(manager, 'indicators', context, limits, client, root, registered, cfg)
    context.update(variables['parsed'])
    base_variables = object_digest(variables['parsed'])
    restore_revisions(root, context, base_variables)
    attempts = cfg['retry']['max_attempts_per_stage']
    for _ in range(attempts + 1):
        manager.state('stage1_generating')
        combined, sources, code_inputs = {'codes': []}, [], {}
        initial = initial_code_batches(manager, context, limits, client, root, registered, cfg)
        for node in context['indicators']:
            local = {'data_schema': schema, 'phenomena': context['phenomena'], 'indicators': [node]}
            value, identity = generate_task(manager, 'codes', local, limits, client, root, registered, cfg,
                item=node['indicator_id'], initial=initial.get(node['indicator_id']))
            code_inputs[node['indicator_id']] = identity
            combined['codes'].extend(value['parsed']['codes'])
            sources.append({'generation_call': value['call'], 'response_sha256': digest(Path(value['call']) / 'response.txt'),
                            'indicator_ids': [node['indicator_id']]})
        context.update(combined)
        assembly_root = root / 'internal/stage1/assemblies' / object_digest({'codes': combined, 'sources': sources})
        _, code_call = generation.assemble_batches('codes', registered['text'], context, limits, client,
                                                   assembly_root, combined, sources)
        build = root / 'internal/stage1/builds' / object_digest({'definitions': context['indicators'], 'codes': combined})
        build.mkdir(parents=True, exist_ok=True); context['merged_edges'] = []
        graph = assemble_graph(context, str(assembly_root / code_call), build)
        save_json(root / 'internal/stage1/current_candidate.json', graph)
        manager.state('stage1_validating')
        approved_path = Path(review_file or cfg['stage1']['review_file'] or root / 'internal/stage1/review.json').resolve()
        approvals, pending = reviewed_approvals(graph, approved_path, root / 'internal/stage1')
        if pending:
            manager.state('review_required', indicator_ids=[p['indicator_id'] for p in pending])
            return {'early_report': _report(root, 'review_required', started, scenario=metadata['scenario'], seeds=[r['seed'] for r in records],
                           review_request=str(root / 'internal/stage1/review_request.json'))}
        rejected = (approvals or {}).get('rejections', {})
        if rejected:
            if not cfg['retry']['retry_invalid_code']:
                raise StageFailure('Code review rejected an implementation; code regeneration is disabled by configuration')
            definition_issues = read_json(root / 'internal/stage1/review_request.json')['definition_repairs']
            if definition_issues:
                repair_definitions(manager,root,context,definition_issues,base_variables,limits,client,registered,cfg,generate_task)
            for iid, rejection in rejected.items():
                if iid in definition_issues: continue
                manager.invalidate('code_' + iid, code_inputs[iid], [issue('codes', 'code_definition_mismatch', rejection['reason'], iid)])
            continue
        reports, repair = [], {}
        for run in runs:
            for node in graph['nodes']:
                iid = node['indicator_id']; rid = run['manifest']['run_id']
                identity = {'indicator_id': iid, 'definition': definition_hash_for_node(node), 'code': node['code_sha256'],
                    'run': run['data_hashes'], 'approval': (approvals or {}).get('code_sha256', {}).get(iid),
                    'reviewer': (approvals or {}).get('reviewer'), 'settings': limits.summary()}
                def execution(folder, previous, node=node, run=run):
                    result = execute_indicator(node, run, build, limits, approvals)
                    if result.get('series_file'): result['series_file'] = str((build / result['series_file']).resolve())
                    return result
                def validate_execution(record):
                    if record.get('series_file') and digest(record['series_file']) != record['series_sha256']:
                        raise ValueError('Computed indicator observations changed')
                record = manager.run('execute_' + iid + '_' + rid, identity, execution, validator=validate_execution)
                reports.append(record)
                if record.get('error_type') == 'execution_or_validation_error' and record.get('execution_started'):
                    if not any(cause in record.get('error', '') for cause in ('insufficient actual observations', 'TimeoutExpired', 'MemoryError')):
                        repair[iid] = [issue('codes', 'indicator_execution_failure', record['error'], iid)]
        save_json(build / 'execution_report.json', reports)
        executable = export_graphs(graph, reports, [r['manifest']['run_id'] for r in runs], build)
        save_json(root / 'internal/stage1/latest_execution.json', {'candidate_nodes': len(graph['nodes']),
            'candidate_edges': len(graph['edges']), 'execution_reports': reports, 'build': str(build)})
        if repair and cfg['retry']['retry_invalid_code']:
            for iid, issues in repair.items(): manager.invalidate('code_' + iid, code_inputs[iid], issues)
            continue
        admission = adapt_graph(executable, dcfg, base_dir=build)
        save_json(build / 'pre_edge_m1_admission.json', admission)
        configuration_errors = {iid:value for iid,value in admission['invalid_nodes'].items() if value['error_type']=='configuration_error'}
        if configuration_errors: raise StageFailure(f'Analysis configuration contradicts predeclared contracts: {configuration_errors}')
        definitions_invalid = {iid:value['reason'] for iid,value in admission['invalid_nodes'].items()
            if value['error_type']=='definition_contract_error'}
        if definitions_invalid and limits.require_analysis_contract:
            repair_definitions(manager,root,context,definitions_invalid,base_variables,limits,client,registered,cfg,generate_task)
            continue
        contract_errors = {iid: value for iid, value in admission['invalid_nodes'].items()
                           if value['error_type']=='implementation_contract_error'}
        if contract_errors:
            for iid, failure in contract_errors.items():
                manager.invalidate('code_' + iid, code_inputs[iid], [issue('codes', 'output_contract_mismatch', failure['reason'], iid)])
            continue
        if limits.require_analysis_contract:
            admitted = set(admission['valid_nodes'])
            selected = [n for n in executable['nodes'] if n['node_id'] in admitted]
            counts = {scale: sum(n['scale'] == scale for n in selected) for scale in ('micro', 'meso', 'macro')}
            phenomenon_missing = {p['phenomenon_id']: sorted({'micro','meso','macro'} -
                {n['scale'] for n in selected if n['phenomenon_id'] == p['phenomenon_id']}) for p in context['phenomena']}
            save_json(root / 'internal/validation/scale_coverage.json', {'generated': {
                scale: sum(n['scale'] == scale for n in context['indicators']) for scale in counts},
                'computed': {scale: sum(n['scale'] == scale for n in executable['nodes']) for scale in counts},
                'm1_admitted': counts, 'm1_rejections': admission['invalid_nodes'],
                'missing_phenomenon_scales': phenomenon_missing,
                'minimum_per_scale': limits.min_indicators_per_scale, 'target_per_scale': limits.target_indicators_per_scale})
            if any(count < limits.min_indicators_per_scale for count in counts.values()) or any(phenomenon_missing.values()):
                manager.state('failed', reason='insufficient_research_scale_coverage', counts=counts)
                return {'early_report': _report(root, 'data_insufficient', started, scenario=metadata['scenario'],
                    seeds=[r['seed'] for r in records], scale_counts=counts, missing_phenomenon_scales=phenomenon_missing,
                    invalid_nodes=admission['invalid_nodes'],
                    reason='Insufficient valid analysis variables; no LLM request follows constant/missing/short-data rejection')}
            # Edges refer only to actual M1-admissible mathematical objects. Original
            # rejected definitions/code/results remain inside the preceding build.
            edge_context = {**context, 'indicators': [n for n in context['indicators'] if n['indicator_id'] in admitted]}
        else:
            edge_context = context
        calls = {}
        for stage in ('edges_upward', 'edges_downward', 'edges_intrascale'):
            value, _ = generate_task(manager, stage, edge_context, limits, client, root, registered, cfg)
            edge_context[stage] = value['parsed']['edges']; calls[stage] = value['call']
            assembly = Path(value['call']) / 'assembly.json'
            if assembly.exists(): edge_context.setdefault('edge_origins', {})[stage] = read_json(assembly)['edge_origins']
        edge_context['merged_edges'], merge_audit = merge_candidate_edges(edge_context, calls, limits)
        graph = assemble_graph(edge_context, str(assembly_root / code_call), build)
        save_json(build / 'edge_merge_report.json', merge_audit)
        executable = export_graphs(graph, reports, [r['manifest']['run_id'] for r in runs], build)
        save_json(root / 'internal/stage1/latest_execution.json', {'candidate_nodes': len(context['indicators']),
            'candidate_edges': len(graph['edges']), 'execution_reports': reports, 'build': str(build),
            'phase': 'pre_edge_execution_and_M1_then_semantic_edges', 'analysis_admission': str(build / 'pre_edge_m1_admission.json')})
        for node in executable['nodes']:
            node['code_file'] = str((build / node['code_file']).resolve())
        executable['provenance'] = {'scenario': metadata['scenario'], 'original_scenario': str(root / 'input/scenario.md'),
                'scenario_sha256': registered['scenario_sha256'], 'client_mode': client.mode, 'llm': cfg['_llm_identity'],
            'run_records': records, 'candidate_graph': artifact_reference(build / 'candidate_graph.json'),
            'review_file': artifact_reference(approved_path) if approved_path.is_file() else None,
            'stage1_algorithms': _sources('causal_graph')}
        validate_stage1(executable)
        official = build / 'stage1_validated.json'; save_json(official, executable)
        publish(official, root / 'stage1_graph.json'); manager.state('stage1_ready', output=artifact_reference(root / 'stage1_graph.json'))
        break
    else: raise StageFailure('Code repair budget exhausted')

    result = {'graph': graph, 'executable': executable, 'reused': False}
    dependencies = [artifact_reference(p) for task in manager.root.iterdir() if task.is_dir() and
        (task.name in ('phenomena','indicators') or task.name.startswith(('code_', 'edges_')))
        for p in task.rglob('*') if p.is_file() and p.name in ('response.txt','actual_prompt.json','result.json','validation.json')]
    save_json(ready_file, {'identity': stage1_identity, 'published': artifact_reference(root / 'stage1_graph.json'),
                          'candidate': artifact_reference(build / 'candidate_graph.json'), 'dependencies': dependencies})
    return result


def run_full_pipeline(scenario=None, *, resume=None, config=None, overrides=None, output=None,
                      review_file=None, client=None, run_function=None, stage2_function=None):
    """Run or resume from one registered scenario; dependencies can be injected in tests."""
    started = time.monotonic()
    if bool(scenario) == bool(resume): raise ValueError('Provide scenario OR resume')
    if resume:
        root = filesystem_path(resume); metadata = read_json(root / 'internal/experiment.json')
        identity_file = root/'internal/experiment.identity.json'
        if identity_file.exists(): verify_reference(read_json(identity_file))
        cfg = load_config(overrides=metadata['config'])
        if config or overrides: raise ValueError('Resume uses saved configuration; start a new experiment to change budgets/model')
        if digest(root / 'input/scenario.md') != metadata['scenario_sha256']: raise ValueError('Saved scenario changed')
        registered = match_scenario(root / 'input/scenario.md')
    else:
        cfg = load_config(config, overrides)
        registered = match_scenario(scenario)
        root = filesystem_path(output or ROOT / cfg['output']['root'] / (time.strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8]))
        root.mkdir(parents=True, exist_ok=False)
        (root / 'input').mkdir(); shutil.copyfile(scenario, root / 'input/scenario.md')
        effective = root / 'internal/config_effective.json'; save_json(effective, cfg)
        metadata = {'created_at': now(), 'config': cfg, 'scenario_sha256': registered['scenario_sha256'],
                    'llm_client_mode':getattr(client,'mode','live_api'),
                    'config_sources': {'default': artifact_reference(Path(__file__).with_name('config.yaml')),
                        'supplied': artifact_reference(config) if config else None, 'effective': artifact_reference(effective)},
                    'scenario': {k: v for k, v in registered.items() if k != 'text'}}
        save_json(root / 'internal/experiment.json', metadata)
        save_json(root/'internal/experiment.identity.json',artifact_reference(root/'internal/experiment.json'))
    manager = StageManager(root, cfg['retry']['max_attempts_per_stage'])
    (root / 'internal/logs').mkdir(parents=True, exist_ok=True)
    lock = root / 'internal/.pipeline.lock'
    if lock.exists():
        import psutil
        saved = read_json(lock)
        if psutil.pid_exists(saved['pid']): raise ValueError(f'Experiment already running (PID {saved["pid"]})')
        lock.rename(root / 'internal/logs' / ('stale_lock_' + uuid.uuid4().hex + '.json'))
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('x', encoding='utf-8') as handle: json.dump({'pid': os.getpid(), 'at': now()}, handle)
    try:
        llm = load_llm(ROOT / cfg['stage1']['llm_config'])
        cfg['_llm_identity'] = llm.summary()
        base = load_pipeline(ROOT / cfg['stage1']['pipeline_config'])
        limits = replace(base, **{**cfg['stage1']['pipeline_overrides'], 'execution_mode': 'trusted_reviewed'})
        # Validate overrides through the existing configuration loader, without changing it.
        save_json(root / 'internal/stage1/settings.json', limits.summary())
        snapshot = root / 'internal/stage1/settings.yaml'; snapshot.write_text(yaml.safe_dump(limits.summary()), encoding='utf-8')
        limits = load_pipeline(snapshot)
        if cfg['experiment_mode'] == 'research' and (limits.min_indicators_per_scale < 4 or
                limits.target_indicators_per_scale < 6 or not limits.require_analysis_contract):
            raise ValueError('Research mode requires >=4 variables/scale, target >=6/scale and explicit analysis contracts; 3-node budgets require interface_test')
        client = client or LLMClient(llm)
        if cfg['experiment_mode']=='research' and client.mode!='live_api':
            raise ValueError('Research experiments require the real API client; mock clients belong to explicit interface_test experiments')
        if metadata.get('llm_client_mode',client.mode) != client.mode:
            raise ValueError('Resume cannot silently switch the original LLM client mode')
        if client.mode == 'live_api': load_configured_credential(cfg, llm)
        dcfg = discovery_settings(ROOT / cfg['stage2']['config'])
        dcfg = discovery_settings({**dcfg, **{k: {**dcfg[k], **v} if isinstance(v, dict) else v for k, v in cfg['stage2']['overrides'].items()}})
        binding = {'llm': llm.summary(), 'stage1_settings': limits.summary(), 'stage2_settings': dcfg,
                   'model_sources': source_identity(registered['model'])}
        bound_file = root / 'internal/config_identity.json'
        if bound_file.exists() and read_json(bound_file) != binding:
            raise ValueError('Saved model/configuration sources changed; start a new experiment rather than silently changing a resumed experiment')
        if not bound_file.exists(): save_json(bound_file, binding)
        from causal_graph.pipeline import software_provenance
        save_json(root / 'internal/logs/software' / (uuid.uuid4().hex + '.json'),
                  {**software_provenance(), 'full_pipeline_sources': _sources('full_pipeline')})
        save_json(root / 'internal/stage2/config.json', dcfg)
        records = []; s = deepcopy(cfg['simulation']); cache = ROOT / cfg['output']['root'] / '.simulation_cache'
        if registered['model'] in s['seeds_by_model']:
            s['seeds'] = s['seeds_by_model'][registered['model']]; s['additional_seeds'] = []
        seeds = (s['seeds'] + s['additional_seeds'])[:s['max_total_runs']]
        for number, seed in enumerate(seeds):
            if number >= len(s['seeds']):
                cover = coverage_report(records, dcfg)
                if not s['supplement_for_coverage'] or cover['sufficient_clock_coverage']: break
            scfg = simulation_config(registered, s, seed, root / 'internal/simulation')
            inputs = {'scenario': metadata['scenario'], 'simulation': {k: v for k, v in scfg.items() if k != 'output'},
                      'model_sources': source_identity(registered['model'])}
            def run_action(folder, previous, scfg=scfg):
                result = prepare_run(registered, scfg, cache, s['reuse_matching_runs'], **({'run_function': run_function} if run_function else {}))
                save_json(folder / 'simulation.json', result); return result
            def verify_run(record):
                assert_unchanged([record])
            records.append(manager.run(f'simulation_{seed}', inputs, run_action, validator=verify_run))
        cover = coverage_report(records, dcfg); save_json(root / 'internal/validation/raw_coverage.json', cover)
        manager.state('simulation_ready', seeds=[r['seed'] for r in records], raw_coverage=cover)
        run_identity = {'runs': [r['data_hashes'] for r in records], 'inspector': digest(ROOT / 'causal_graph/inputs.py')}
        runs = manager.run('inspect_inputs', run_identity,
            lambda folder, previous: [r['inspection'] for r in records] if all('inspection' in r for r in records) else
                                     inspect_runs([r['directory'] for r in records]), validator=assert_unchanged)
        def observed_schema(folder, previous):
            old_schema, old_audit = root / 'internal/stage1/data_schema.json', root / 'internal/stage1/data_schema_audit.json'
            # Adopt only actual earlier function outputs bound to the same verified
            # runs and unchanged data_schema source. No model response is altered.
            software = list((root / 'internal/logs/software').glob('*.json'))
            unchanged_source = software and all(read_json(p)['source_sha256']['data_schema.py'] ==
                                               digest(ROOT / 'causal_graph/data_schema.py') for p in software)
            if old_schema.exists() and old_audit.exists() and unchanged_source:
                a, b = read_json(old_schema), read_json(old_audit)
                if object_digest(a) == b['schema_sha256'] and set(b['per_run']) == {r['run_id'] for r in records}:
                    save_json(folder / 'adoption.json', {'kind': 'verified_previous_observed_schema',
                        'schema': artifact_reference(old_schema), 'audit': artifact_reference(old_audit), 'run_identity': run_identity})
                    return {'schema': a, 'audit': b}
            a, b = build_data_schema(runs)
            return {'schema': a, 'audit': b}
        observed = manager.run('observed_schema', {**run_identity, 'builder': digest(ROOT / 'causal_graph/data_schema.py')}, observed_schema)
        schema, schema_audit = observed['schema'], observed['audit']
        save_json(root / 'internal/stage1/data_schema.json', schema)
        save_json(root / 'internal/stage1/data_schema_audit.json', schema_audit)
        import gc
        import pyarrow as pa
        gc.collect(); pa.default_memory_pool().release_unused()
        first = _run_stage1(manager, root, registered, metadata, records, runs, schema, cfg, limits, client, review_file, started, dcfg)
        if 'early_report' in first: return first['early_report']
        graph, executable = first['graph'], first['executable']
        if first['reused']: manager.state('stage1_ready', reused=True, output=artifact_reference(root / 'stage1_graph.json'))
        assert_unchanged(runs)
        # M1 is reused before and inside stage two; its output never feeds generation.
        admission = adapt_graph(root / 'stage1_graph.json', dcfg)
        save_json(root / 'internal/validation/stage2_admission.json', admission)
        manager.state('stage2_running')
        stage2_input = {'stage1': artifact_reference(root / 'stage1_graph.json'), 'config': dcfg,
                        'algorithm_sources': _sources('causal_discovery')}
        def analysis(folder, previous):
            function = stage2_function or discover
            result = function(root / 'stage1_graph.json', folder / 'final_causal_graph.json', config=dcfg)
            return {'file': artifact_reference(folder / 'final_causal_graph.json'), 'report': result['report']}
        def validate_analysis(value):
            verify_reference(value['file'])
            graph = read_json(value['file']['path']); path = Path(value['file']['path'])
            audit = path.parent / (path.stem + '_audit')
            validate_stage2(graph, executable, audit)
            # Reuse M5 to trace every accepted edge back to the saved numerical
            # records and corrected tests; this performs no new statistical fit.
            from causal_discovery.m5_graph import integrate_graph
            replay = integrate_graph(executable, read_json(audit / 'm1_data.json'),
                read_json(audit / 'm2_lag_results.json'), read_json(audit / 'm3_granger_results.json'),
                read_json(audit / 'm4_pid_results.json'), dcfg)['graph']
            if graph['nodes'] != replay['nodes'] or graph['edges'] != replay['edges']:
                raise ValueError('Final graph cannot be reproduced from the saved M1–M5 numerical evidence')
        result = manager.run('stage2', stage2_input, analysis, validator=validate_analysis)
        manager.state('stage2_validating')
        validate_analysis(result); publish(Path(result['file']['path']), root / 'final_causal_graph.json')
        assert_unchanged(runs)
        manager.state('completed', outputs=[artifact_reference(root / p) for p in ('stage1_graph.json', 'final_causal_graph.json')])
        return _report(root, 'completed', started, scenario=metadata['scenario'], seeds=[r['seed'] for r in records],
            stage2_outcome=result['report']['status'], invalid_nodes=admission['invalid_nodes'],
            raw_candidate_nodes=len(graph['nodes']), raw_candidate_edges=len(graph['edges']),
            actual_valid_nodes=len(admission['valid_nodes']), scientific_scope='observational predictive and joint information; not structural causal truth')
    except BaseException as exc:
        manager.state('failed', reason=f'{type(exc).__name__}: {exc}')
        failure = root / 'internal/logs' / ('failure_' + uuid.uuid4().hex + '.txt')
        failure.write_text(traceback.format_exc(), encoding='utf-8')
        _report(root, 'failed', started, error=f'{type(exc).__name__}: {exc}', scenario=metadata['scenario'])
        raise
    finally:
        lock.unlink(missing_ok=True)


def definition_hash_for_node(node):
    from .validators import definition_hash
    return definition_hash(node)


def filesystem_path(path):
    """Keep nested immutable audits usable under Windows' legacy MAX_PATH limit."""
    value = str(Path(path).resolve())
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return Path(value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--scenario', type=Path); mode.add_argument('--resume', type=Path)
    parser.add_argument('--config', type=Path); parser.add_argument('--review-file', type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_full_pipeline(args.scenario, resume=args.resume, config=args.config, review_file=args.review_file)
    except Exception as exc:
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == '__main__': main()
