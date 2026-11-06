"""Ten inspectable stage-one steps with resumable generation and provenance."""
from dataclasses import asdict
import importlib.metadata
from pathlib import Path
import subprocess
import platform
import sys
import traceback
import uuid

from . import __version__
from .generation import identify_phenomena, define_indicators, generate_codes, propose_edges
from .graph_export import assemble_graph, export_graphs
from .indicator_runner import execute_indicator
from .inputs import inspect_runs, assert_unchanged
from .io import digest, now, object_digest, read_json, save_json
from .llm_client import LLMClient
from .prompts import TEMPLATE_VERSION
from .schemas import SCHEMAS, GRAPH_SCHEMA, EXECUTABLE_SCHEMA


class PipelineFailure(RuntimeError):
    pass


def software_provenance():
    root = Path(__file__).resolve().parent
    hashes = {p.name: digest(p) for p in sorted(root.glob('*.py'))}
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True)
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True, text=True)
    versions = {name: importlib.metadata.version(name) for name in
                ('numpy', 'pandas', 'pyarrow', 'scipy', 'networkx', 'PyYAML', 'jsonschema')}
    return {'package_version': __version__, 'python': sys.version, 'platform': platform.platform(),
            'source_sha256': hashes, 'versions': versions,
            'git_commit': git.stdout.strip() if git.returncode == 0 else None,
            'git_dirty': bool(dirty.stdout.strip()) if dirty.returncode == 0 else None}


def run_pipeline(paths, llm_config, settings, output, *, client=None, resume=False,
                 generate_only=False, approvals=None):
    output = Path(output).resolve()
    if any(output.is_relative_to(Path(p).resolve()) or Path(p).resolve().is_relative_to(output) for p in paths):
        raise ValueError('Experiment output and input run directories must be disjoint')
    if resume:
        if not (output / 'experiment.json').is_file():
            raise ValueError('Cannot resume without experiment.json')
    else:
        output.mkdir(parents=True, exist_ok=False)
    # A file lock is removed even on exceptions; SIGKILL may require manual stale-lock removal.
    lock = output / '.pipeline.lock'
    try:
        lock_handle = lock.open('x')
    except FileExistsError:
        raise ValueError('Experiment is locked; finish the active process or inspect/remove a stale lock') from None
    lock_handle.close()
    report = {'started_at': now(), 'status': 'running', 'steps': [], 'resumed': resume}
    invocation = output / 'invocations' / uuid.uuid4().hex
    invocation.mkdir(parents=True)
    client = client or LLMClient(llm_config)
    metadata = None

    def step(number, name, inputs, outputs, action):
        entry = {'number': number, 'name': name, 'inputs': inputs, 'outputs': outputs,
                 'started_at': now(), 'status': 'running'}
        report['steps'].append(entry)
        save_json(invocation / 'pipeline_report.json', report)
        try:
            value = action()
            entry['status'] = 'success'
            return value
        except BaseException as exc:
            entry.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                         error=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            entry['ended_at'] = now()
            save_json(invocation / 'pipeline_report.json', report)

    try:
        runs = step(1, 'read_fixed_scenario_and_verify_runs', [str(p) for p in paths], ['inputs.json', 'scenario.md'],
                    lambda: inspect_runs(paths))
        software = software_provenance()
        # Execution mode may change only via explicit resume; generation identity cannot change.
        generation_settings = {k: asdict(settings)[k] for k in
                               ('max_phenomena', 'max_indicators', 'max_edges', 'generation_attempts')}
        identity = {'inputs': [{k: r[k] for k in ('directory', 'data_hashes')} for r in runs],
                    'llm': llm_config.summary(), 'generation_settings': generation_settings,
                    'prompt_version': TEMPLATE_VERSION, 'source_sha256': software['source_sha256'],
                    'client_mode': client.mode}
        if resume:
            metadata = read_json(output / 'experiment.json')
            if metadata['identity_sha256'] != object_digest(identity):
                raise ValueError('Resume identity mismatch: inputs/model/config/prompts/source/mode changed')
        else:
            manifest = runs[0]['manifest']
            metadata = {'experiment_id': uuid.uuid4().hex, 'started_at': now(), 'status': 'running',
                        'model_name': manifest['model_name'], 'model_version': manifest['model_version'],
                        'scenario': runs[0]['scenario'], 'llm': llm_config.summary(), 'client_mode': client.mode,
                        'software': software, 'identity': identity, 'identity_sha256': object_digest(identity),
                        'invocations': []}
        metadata['invocations'].append(invocation.relative_to(output).as_posix())
        metadata.update(status='running', pipeline_config=asdict(settings))
        save_json(output / 'experiment.json', metadata)
        save_json(output / 'inputs.json', [{k: v for k, v in r.items() if k != 'scenario_text'} for r in runs])
        (output / 'scenario.md').write_text(runs[0]['scenario_text'], encoding='utf-8')
        save_json(output / 'schemas.json', {'generation': SCHEMAS, 'candidate_graph': GRAPH_SCHEMA,
                                          'executable_graph': EXECUTABLE_SCHEMA})
        save_json(invocation / 'settings.json', {'pipeline': asdict(settings), 'generate_only': generate_only,
                                               'review': approvals})
        context, calls = {}, {}
        for number, name, action in ((2, 'phenomena', identify_phenomena), (3, 'indicators', define_indicators),
                                     (4, 'codes', generate_codes), (5, 'edges', propose_edges)):
            parsed, call = step(number, f'generate_{name}', ['scenario.md', *context],
                                [f'generation/{name}/parsed.json'],
                                lambda fn=action: fn(runs[0]['scenario_text'], context, settings, client, output))
            context.update(parsed)
            calls[name] = call
        graph = step(6, 'validate_and_assemble_candidate', ['generation/*/parsed.json'],
                     ['candidate_graph.json', 'indicator_code/', 'structure_report.json'],
                     lambda: assemble_graph(context, calls['codes'], output))
        save_json(output / 'candidate_graph.json', graph)
        save_json(output / 'structure_report.json', {'valid': True, 'checks': [
            'JSON Schema', 'unique IDs/names', 'references', 'scale direction', 'complete paths',
            'function signatures', 'Python syntax', 'code constraints'], 'generation_calls': calls})
        run_ids = [r['manifest']['run_id'] for r in runs]
        reports = []

        def execute():
            for run in runs:
                for node in graph['nodes']:
                    if generate_only:
                        result = {'run_id': run['manifest']['run_id'], 'indicator_id': node['indicator_id'],
                                  'status': 'not_executed', 'reason': 'explicit_generate_only',
                                  'code_sha256': node['code_sha256'], 'generation_call': node['generation_call']}
                    else:
                        result = execute_indicator(node, run, output, settings, approvals)
                    reports.append(result)
                    save_json(invocation / 'execution_report.json', reports)
            return reports

        step(7, 'execute_indicators', ['indicator_code/', 'inputs.json'], ['execution/', 'indicator_series/'], execute)
        step(8, 'report_computational_validity', ['execution/'], ['execution_report.json'],
             lambda: save_json(output / 'execution_report.json', reports))
        executable = step(9, 'export_semantic_and_executable_graphs', ['candidate_graph.json', 'execution_report.json'],
                          ['candidate_graph.graphml', 'executable_graph.json', 'executable_graph.graphml', 'per_run/'],
                          lambda: export_graphs(graph, reports, run_ids, output))
        step(10, 'finalize_provenance', ['inputs.json'], ['experiment.json', 'artifact_hashes.json'],
             lambda: assert_unchanged(runs))
        report.update(status='generated_only' if generate_only else
                      'completed' if all(r['status'] == 'success' for r in reports) else 'completed_with_failures',
                      successful_calculations=sum(r['status'] == 'success' for r in reports),
                      total_calculations=len(reports), executable_nodes=len(executable['nodes']))
    except BaseException as exc:
        report.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                      error=f'{type(exc).__name__}: {exc}')
        (invocation / 'failure_traceback.txt').write_text(traceback.format_exc(), encoding='utf-8')
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise PipelineFailure(f'{exc}; experiment audit: {output}') from exc
    finally:
        report['ended_at'] = now()
        save_json(invocation / 'pipeline_report.json', report)
        # A rejected resume must not overwrite the original experiment's published state.
        if metadata is not None and invocation.relative_to(output).as_posix() in metadata.get('invocations', []):
            metadata.update(status=report['status'], ended_at=report['ended_at'])
            save_json(output / 'experiment.json', metadata)
            save_json(output / 'pipeline_report.json', report)
            artifacts = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob('*'))
                         if p.is_file() and p.name not in {'.pipeline.lock', 'artifact_hashes.json'} and p.suffix != '.tmp'}
            save_json(output / 'artifact_hashes.json', artifacts)
        elif not resume:
            save_json(output / 'pipeline_report.json', report)
        lock.unlink(missing_ok=True)
    return output
