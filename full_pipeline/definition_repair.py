"""Bounded, immutable local definition revisions; no statistical feedback channel."""
from pathlib import Path

from causal_graph.io import now, object_digest, read_json, save_json
from .stage_manager import StageFailure


def restore_revisions(root: Path, context: dict, base: str) -> None:
    for path in sorted((root / 'internal/stage1/definition_revisions').glob('revision_*.json')):
        revision = read_json(path)
        if revision['base_variables_sha256'] != base: continue
        if object_digest(context['indicators']) != revision['before_sha256']:
            raise StageFailure('Definition revision dependency hash mismatch')
        if object_digest(revision['replacements']) != revision['replacements_sha256']:
            raise StageFailure('Definition repair content changed')
        replacements = {n['indicator_id']: n for n in revision['replacements']}
        context['indicators'] = [replacements.get(n['indicator_id'], n) for n in context['indicators']]
        if object_digest(context['indicators']) != revision['after_sha256']:
            raise StageFailure('Repaired definition set hash mismatch')


def repair_definitions(manager, root, context, issues, base, limits, client, scenario, cfg, generate):
    directory = root / 'internal/stage1/definition_revisions'; files = sorted(directory.glob('revision_*.json'))
    for iid in issues:
        count = sum(iid in {n['indicator_id'] for n in read_json(p)['replacements']} and read_json(p)['base_variables_sha256'] == base for p in files)
        if count >= cfg['retry']['max_attempts_per_stage'] - 1:
            raise StageFailure(f'{iid}: maximum definition revisions exhausted')
    local = {'data_schema':context['data_schema'], 'phenomena':context['phenomena'],
        'existing_indicators':context['indicators'], 'repair_indicator_ids':sorted(issues), 'definition_issues':issues}
    value, _ = generate(manager,'indicators',local,limits,client,root,scenario,cfg)
    replacements = value['parsed']['indicators']; before = object_digest(context['indicators'])
    lookup = {n['indicator_id']:n for n in replacements}
    context['indicators'] = [lookup.get(n['indicator_id'],n) for n in context['indicators']]
    revision = {'at':now(), 'base_variables_sha256':base, 'before_sha256':before,
        'replacements':replacements, 'replacements_sha256':object_digest(replacements),
        'after_sha256':object_digest(context['indicators']), 'generation_call':value['call'], 'issues':issues,
        'reason_scope':'Explicit definition/analysis-contract error only; never lack of significance or constant observed data'}
    save_json(directory / f'revision_{len(files):03d}.json', revision)
