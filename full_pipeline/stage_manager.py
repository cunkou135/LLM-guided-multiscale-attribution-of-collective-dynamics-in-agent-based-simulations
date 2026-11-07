"""Small content-addressed stage journal; raw attempts are immutable."""
from pathlib import Path
import inspect
import traceback
import uuid

from causal_graph.io import digest, now, object_digest, read_json, save_json


class StageFailure(RuntimeError):
    pass


class QualityError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('; '.join(i['message'] for i in issues))


class StageManager:
    def __init__(self, experiment: Path, maximum: int = 3):
        self.experiment = Path(experiment)
        self.root = self.experiment / 'internal/checkpoints'
        self.root.mkdir(parents=True, exist_ok=True)
        self.maximum = maximum

    def state(self, status: str, **details):
        timestamp = now(); current = self.root / 'state.json'
        if current.exists():
            previous = read_json(current)
            save_json(self.root / 'events' / (uuid.uuid4().hex + '.json'), {**previous, 'ended_at': timestamp, 'transition_record': True})
        caller = inspect.currentframe().f_back
        inputs = [artifact_reference(self.experiment / 'input/scenario.md')] if (self.experiment / 'input/scenario.md').exists() else []
        outputs = [artifact_reference(self.experiment / name) for name in ('stage1_graph.json', 'final_causal_graph.json') if (self.experiment / name).exists()]
        entry = {'status': status, 'at': timestamp, 'started_at': timestamp, 'ended_at': timestamp if status in ('completed','failed','review_required') else None,
                 'module': caller.f_globals.get('__name__'), 'function': caller.f_code.co_name,
                 'inputs': inputs, 'outputs': outputs,
                 'passed_checkpoints': [artifact_reference(p) for p in self.root.glob('*/*/checkpoint.json')], **details}
        save_json(self.root / 'events' / (uuid.uuid4().hex + '.json'), entry)
        save_json(self.root / 'state.json', entry)

    def directory(self, name, inputs):
        if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in name):
            raise ValueError('Unsafe task name')
        return self.root / name / object_digest(inputs)

    def invalidate(self, name, inputs, issues):
        directory = self.directory(name, inputs)
        checkpoint = read_json(directory / 'checkpoint.json')
        save_json(directory / 'invalidations' / (checkpoint['attempt'] + '.json'),
                  {'at': now(), 'checkpoint': checkpoint, 'issues': issues})

    def run(self, name, inputs, action, *, validator=None, retry=False, retry_allowed=None):
        """action(attempt_directory, previous_issues) -> JSON result.

        Input changes create new versions and invalidate dependent cache identities.
        Same-identity tampering fails closed instead of silently issuing new calls.
        """
        directory = self.directory(name, inputs); directory.mkdir(parents=True, exist_ok=True)
        checkpoint = directory / 'checkpoint.json'
        previous = []
        if checkpoint.exists():
            saved = read_json(checkpoint)
            if saved['input_sha256'] != object_digest(inputs): raise StageFailure('Checkpoint input hash changed')
            for relative, expected in saved['artifacts'].items():
                if digest(directory / relative) != expected: raise StageFailure(f'{name}: checkpoint artifact changed: {relative}')
            invalidation = directory / 'invalidations' / (saved['attempt'] + '.json')
            if not invalidation.exists():
                value = read_json(directory / saved['result'])
                try:
                    if validator: validator(value)
                    return value
                except QualityError as exc:
                    self.invalidate(name, inputs, exc.issues)
            previous = read_json(invalidation)['issues']
        attempts = sorted(directory.glob('attempt_*'))
        if attempts and not previous:
            last = attempts[-1] / 'audit.json'
            previous = read_json(last).get('issues', []) if last.exists() else [
                {'type': 'interrupted', 'stage': name, 'message': 'Previous attempt interrupted before audit completion'}]
        while len(attempts) < self.maximum:
            attempt = directory / f'attempt_{len(attempts):03d}'; attempt.mkdir(exist_ok=False)
            audit = {'task': name, 'function': getattr(action, '__qualname__', str(action)), 'inputs': inputs,
                     'module': getattr(action, '__module__', None), 'retry_count': len(attempts),
                     'input_sha256': object_digest(inputs), 'attempt': len(attempts) + 1,
                     'started_at': now(), 'status': 'running'}
            save_json(attempt / 'audit.json', audit)
            try:
                value = action(attempt, previous)
                if validator: validator(value)
                save_json(attempt / 'result.json', value)
                audit.update(status='passed', ended_at=now(), output_sha256=digest(attempt / 'result.json'))
                save_json(attempt / 'audit.json', audit)
                artifacts = {p.relative_to(directory).as_posix(): digest(p) for p in sorted(attempt.rglob('*')) if p.is_file()}
                save_json(checkpoint, {'input_sha256': object_digest(inputs), 'attempt': attempt.name,
                    'result': (attempt / 'result.json').relative_to(directory).as_posix(), 'artifacts': artifacts})
                return value
            except BaseException as exc:
                previous = exc.issues if isinstance(exc, QualityError) else [
                    {'type': 'engineering_error', 'stage': name, 'message': f'{type(exc).__name__}: {exc}'}]
                audit.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', ended_at=now(), issues=previous)
                save_json(attempt / 'audit.json', audit)
                (attempt / 'traceback.txt').write_text(traceback.format_exc(), encoding='utf-8')
                if not isinstance(exc, Exception): raise
                attempts.append(attempt)
                if not retry or retry_allowed and not retry_allowed(previous):
                    raise StageFailure(f'{name}: {exc}') from exc
        raise StageFailure(f'{name}: maximum {self.maximum} attempts exhausted; all original responses retained')


def artifact_reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': digest(path)}


def verify_reference(reference):
    if digest(reference['path']) != reference['sha256']:
        raise StageFailure(f'Artifact SHA-256 mismatch: {reference["path"]}')
