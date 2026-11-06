"""Steps 2–6: separate, checkpointed model calls and structure reports."""
from pathlib import Path

from .io import digest, object_digest, read_json, save_json
from .prompts import build_messages, TEMPLATE_VERSION
from .schemas import EDGE_STAGES
from .schemas import parse_response, validate_stage


def generate_stage(stage, scenario, context, limits, client, root):
    directory = Path(root) / 'generation' / stage
    directory.mkdir(parents=True, exist_ok=True)
    messages = build_messages(stage, scenario, context, limits)
    schema = context.get('data_schema')
    provenance = {'data_schema_version': schema['schema_version'] if schema else None,
                  'data_schema_sha256': object_digest(schema) if schema else None,
                  'schema_in_prompt': stage in ('indicators', 'codes'), 'template_version': TEMPLATE_VERSION}
    request_hash = object_digest({'messages': messages, 'provenance': provenance})
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
    return generate_stage('codes', scenario, context, limits, client, root)


def propose_upward_edges(scenario, context, limits, client, root):
    return generate_stage('edges_upward', scenario, context, limits, client, root)


def propose_downward_edges(scenario, context, limits, client, root):
    return generate_stage('edges_downward', scenario, context, limits, client, root)


def propose_intrascale_edges(scenario, context, limits, client, root):
    return generate_stage('edges_intrascale', scenario, context, limits, client, root)
