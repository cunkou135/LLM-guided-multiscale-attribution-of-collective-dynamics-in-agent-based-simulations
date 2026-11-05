"""Read immutable scenario version 1.0 and verify its registered bytes."""
import hashlib
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent
PINNED = {
    'SCENARIO-SCHELLING-001': ('schelling.md', '820cbcc69f941c2b468f31a7b1ef22488a4271423bd37bbbf232badda2992b3d'),
    'SCENARIO-COVASIM-001': ('covasim.md', '7a477bf35fd70f0d9847cd260efd2f05f5d7ec1d6055aeb4f954e923412f8c6b'),
}


def load_scenario(scenario_id, directory=None):
    """Verify both original scenarios before returning one text and provenance."""
    root = Path(directory) if directory is not None else ROOT
    registry = yaml.safe_load((root / 'manifest.yaml').read_text(encoding='utf-8'))['scenarios']
    sums = dict((name, digest) for digest, name in (line.split() for line in (root / 'SHA256SUMS').read_text().splitlines()))
    if set(registry) != set(PINNED):
        raise ValueError('Scenario registry differs from fixed version 1.0')
    for sid, (name, expected) in PINNED.items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        entry = registry[sid]
        if actual != expected or entry['sha256'] != expected or sums.get(name) != expected or entry['version'] != '1.0' or entry['path'] != f'scenarios/{name}':
            raise ValueError(f'Scenario integrity mismatch: {sid}, file={name}, expected={expected}, actual={actual}; formal run refused')
    if scenario_id not in PINNED:
        raise ValueError(f'Unknown scenario: {scenario_id}')
    name, digest = PINNED[scenario_id]
    return dict(scenario_id=scenario_id, scenario_version='1.0', scenario_sha256=digest,
                text=(root / name).read_text(encoding='utf-8'))
