"""Steps 2–6: separate, checkpointed model calls and structure reports."""
from pathlib import Path
import uuid
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

from .io import digest, now, object_digest, read_json, save_json
from .prompts import build_messages, template_version
from .schemas import EDGE_STAGES, classify_direction
from .schemas import parse_response, validate_stage


def stage_request(stage, scenario, context, limits):
    messages = build_messages(stage, scenario, context, limits)
    schema = context.get('data_schema')
    provenance = {'data_schema_version': schema['schema_version'] if schema else None,
                  'data_schema_sha256': object_digest(schema) if schema else None,
                  'schema_in_prompt': stage in ('indicators', 'codes'), 'template_version': template_version(limits) +
                  ('/edge-partition-1' if 'edge_source_ids' in context else '')}
    request_hash = object_digest({'messages': messages, 'provenance': provenance})
    return messages, provenance, request_hash


def generate_stage(stage, scenario, context, limits, client, root, *, directory=None):
    directory = Path(directory) if directory is not None else Path(root) / 'generation' / stage
    directory.mkdir(parents=True, exist_ok=True)
    messages, provenance, request_hash = stage_request(stage, scenario, context, limits)
    checkpoint = directory / 'checkpoint.json'
    if checkpoint.exists():
        saved = read_json(checkpoint)
        if saved['request_sha256'] != request_hash:
            raise ValueError(f'{stage}: checkpoint prompt mismatch')
        parsed = read_json(directory / 'parsed.json')
        if object_digest(parsed) != saved['parsed_sha256'] or not validate_stage(stage, parsed, context, limits)['valid']:
            raise ValueError(f'{stage}: checkpoint content changed or invalid')
        response = Path(root) / saved['generation_call'] / 'response.txt'
        if digest(response) != saved['response_sha256']:
            raise ValueError(f'{stage}: original response changed')
        return parsed, saved['generation_call']
    if (stage == 'codes' or stage in EDGE_STAGES and 'edge_source_ids' in context) and getattr(client, 'revalidate_saved', False):
        artifacts = read_json(Path(root) / 'artifact_hashes.json')
        for call in sorted(directory.glob('attempt_*')):
            if not (call / 'response.txt').is_file() or read_json(call / 'prompt.json') != messages:
                continue
            for filename in ('response.txt', 'prompt.json'):
                path = call / filename
                expected = artifacts.get(path.relative_to(root).as_posix())
                if expected is None or digest(path) != expected:
                    raise ValueError('Original generation artifact hash mismatch during revalidation')
            try:
                parsed = parse_response((call / 'response.txt').read_text(encoding='utf-8'))
                report = validate_stage(stage, parsed, context, limits)
            except (ValueError, TypeError) as exc:
                report = {'valid': False, 'errors': [str(exc)]}
            report.update(rechecked_at=now(), original_response_sha256=digest(call / 'response.txt'),
                          validator_source_sha256={name: digest(Path(__file__).with_name(name))
                                                   for name in ('schemas.py', 'code_contract.py')})
            validation = call / ('revalidation_' + uuid.uuid4().hex + '.json')
            save_json(validation, report)
            if report['valid']:
                save_json(directory / 'parsed.json', parsed)
                relative = call.relative_to(root).as_posix()
                save_json(checkpoint, {'request_sha256': request_hash, 'parsed_sha256': object_digest(parsed),
                    'response_sha256': digest(call / 'response.txt'), 'generation_call': relative,
                    'validation_file': validation.relative_to(root).as_posix()})
                return parsed, relative
    previous = len(list(directory.glob('attempt_*')))
    for attempt in range(previous, previous + limits.generation_attempts):
        call = directory / f'attempt_{attempt:03d}'
        call.mkdir(exist_ok=False)
        save_json(call / 'prompt.json', messages)
        save_json(call / 'input_provenance.json', provenance)
        # Transport persists every HTTP attempt under its own directory.
        try:
            raw = client.complete(messages, call / 'transport')
        except Exception as exc:
            save_json(call / 'validation.json', {'valid': False, 'errors': [f'{type(exc).__name__}: {exc}']})
            raise
        (call / 'response.txt').write_text(raw, encoding='utf-8')
        try:
            parsed = parse_response(raw)
            report = validate_stage(stage, parsed, context, limits)
            save_json(call / 'parsed.json', parsed)
        except (ValueError, TypeError) as exc:
            report = {'valid': False, 'errors': [f'{type(exc).__name__}: {exc}']}
        save_json(call / 'validation.json', report)
        if report['valid']:
            save_json(directory / 'parsed.json', parsed)
            relative = str(call.relative_to(root)).replace('\\', '/')
            save_json(checkpoint, {'request_sha256': request_hash, 'parsed_sha256': object_digest(parsed),
                                   'response_sha256': digest(call / 'response.txt'), 'generation_call': relative})
            return parsed, relative
        # No log feedback, field catalog, source, errors or reference answers in regeneration.
    raise ValueError(f'{stage}: structural validation failed; original attempts retained in {directory}')


def identify_phenomena(scenario, context, limits, client, root):
    return generate_stage('phenomena', scenario, context, limits, client, root)


def define_indicators(scenario, context, limits, client, root):
    return generate_stage('indicators', scenario, context, limits, client, root)


def generate_codes(scenario, context, limits, client, root):
    size = limits.code_batch_size
    if not size or len(context['indicators']) <= size:
        return generate_stage('codes', scenario, context, limits, client, root)
    directory = Path(root) / 'generation/codes'
    combined, sources = {'codes': []}, []
    for number, offset in enumerate(range(0, len(context['indicators']), size)):
        batch_context = {**context, 'indicators': context['indicators'][offset:offset + size]}
        batch_dir = directory / 'batches' / f'batch_{number:03d}'
        parsed, call = generate_stage('codes', scenario, batch_context, limits, client, root, directory=batch_dir)
        combined['codes'].extend(parsed['codes'])
        sources.append({'generation_call': call, 'response_sha256': digest(Path(root) / call / 'response.txt'),
                        'indicator_ids': [n['indicator_id'] for n in batch_context['indicators']]})
        validation_file = read_json(batch_dir / 'checkpoint.json').get('validation_file')
        if validation_file:
            sources[-1]['validation_file'] = validation_file
    return assemble_batches('codes', scenario, context, limits, client, root, combined, sources)


def assemble_batches(stage, scenario, context, limits, client, root, combined, sources, origins=None):
    directory = Path(root) / 'generation' / stage
    report = validate_stage(stage, combined, context, limits)
    if not report['valid']:
        raise ValueError('Combined code batches failed validation: ' + str(report['errors']))
    checkpoint = directory / 'checkpoint.json'
    if checkpoint.exists():
        parsed, call = generate_stage(stage, scenario, context, limits, client, root)
        saved = read_json(checkpoint)
        if parsed != combined or saved.get('batch_sources') != sources:
            raise ValueError('Combined code checkpoint differs from its original batch responses')
        return parsed, call
    assembly = directory / 'local_batch_assembly'
    assembly.mkdir(parents=True, exist_ok=True)
    # This file is explicitly a local assembly, never an original model response.
    save_json(assembly / 'response.txt', combined)
    save_json(assembly / 'parsed.json', combined)
    save_json(assembly / 'validation.json', report)
    save_json(assembly / 'assembly.json', {'kind': 'deterministic_local_batch_assembly', 'model_request_made': False,
                                          'sources': sources, 'edge_origins': origins})
    messages, provenance, request_hash = stage_request(stage, scenario, context, limits)
    save_json(assembly / 'prompt.json', messages)
    save_json(assembly / 'input_provenance.json', {**provenance, 'kind': 'assembly_contract_not_sent_to_model'})
    save_json(directory / 'parsed.json', combined)
    call = assembly.relative_to(root).as_posix()
    save_json(checkpoint, {'request_sha256': request_hash, 'parsed_sha256': object_digest(combined),
                          'response_sha256': digest(assembly / 'response.txt'), 'generation_call': call,
                          'batch_sources': sources})
    return combined, call


def generate_edges(stage, scenario, context, limits, client, root):
    directory = Path(root) / 'generation' / stage
    checkpoint = directory / 'checkpoint.json'
    if limits.max_indicators < 48 or limits.max_edges <= 180:
        return generate_stage(stage, scenario, context, limits, client, root)
    if checkpoint.exists() and 'batch_sources' not in read_json(checkpoint):
        return generate_stage(stage, scenario, context, limits, client, root)
    direction = EDGE_STAGES[stage]
    nodes = context['indicators']
    sources = [n['indicator_id'] for n in nodes if any(t['indicator_id'] != n['indicator_id'] and
               classify_direction(n['scale'], t['scale']) == direction for t in nodes)]
    total = limits.max_edges // 3
    count = min(len(sources), (total + 59) // 60)
    if count < 2:
        return generate_stage(stage, scenario, context, limits, client, root)
    plan = [{'source_ids': sources[i::count], 'edge_budget': total // count + (i < total % count)} for i in range(count)]
    save_json(directory / 'partition_plan.json', {'direction': direction, 'direction_budget': total,
              'all_eligible_source_ids': sources, 'partitions': plan,
              'rule': 'disjoint source partitions; complete target definitions; at most 60 edges per response'})
    def generate_batch(item):
        number, part = item
        batch_context = {**context, 'edge_source_ids': part['source_ids']}
        batch_limits = replace(limits, max_edges=part['edge_budget'] * 3)
        return generate_stage(stage, scenario, batch_context, batch_limits, client, root,
                              directory=directory / 'batches' / f'batch_{number:03d}')
    with ThreadPoolExecutor(max_workers=min(4, count)) as workers:
        results = list(workers.map(generate_batch, enumerate(plan)))
    combined, provenance, origins = {'edges': []}, [], []
    for number, (parsed, call) in enumerate(results):
        provenance.append({'generation_call': call, 'response_sha256': digest(Path(root) / call / 'response.txt'), **plan[number]})
        for index, edge in enumerate(parsed['edges']):
            local_id = f'b{number:02d}_r{index:04d}'
            combined['edges'].append({**edge, 'edge_id': local_id})
            origins.append({'stage': stage, 'call': call, 'original_edge_id': edge['edge_id'], 'row_index': index})
    return assemble_batches(stage, scenario, context, limits, client, root, combined, provenance, origins)


def propose_upward_edges(scenario, context, limits, client, root):
    return generate_edges('edges_upward', scenario, context, limits, client, root)


def propose_downward_edges(scenario, context, limits, client, root):
    return generate_edges('edges_downward', scenario, context, limits, client, root)


def propose_intrascale_edges(scenario, context, limits, client, root):
    return generate_edges('edges_intrascale', scenario, context, limits, client, root)
