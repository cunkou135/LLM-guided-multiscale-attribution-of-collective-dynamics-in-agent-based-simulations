"""Read immutable, versioned scenarios and verify all registered bytes."""
import hashlib
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent
PINNED = {
    'SCENARIO-SCHELLING-001': ('schelling.md', '820cbcc69f941c2b468f31a7b1ef22488a4271423bd37bbbf232badda2992b3d'),
    'SCENARIO-COVASIM-001': ('covasim.md', '7a477bf35fd70f0d9847cd260efd2f05f5d7ec1d6055aeb4f954e923412f8c6b'),
}
V2_PINNED = {
    'SCENARIO-SCHELLING-001': ('v2/schelling.md', 'ecfa1373637c172b6e1ab2786a9d4b803ea9f58ae65963f2d883326dde85d4c7'),
    'SCENARIO-COVASIM-001': ('v2/covasim.md', '50bcd64c7fbd6ca511fa899e452450013a0a59db3ec235b5b7350ec53f381cde'),
}

FISH_PINNED = ('fish.md', 'f2714fa2fd10ebc949f2f91843387ad5965f6eca75a4cb60496a4f6c7642a936')


def load_scenario(scenario_id, directory=None, version='2.0'):
    """Verify both generations before returning explicitly versioned provenance."""
    root = Path(directory) if directory is not None else ROOT
    registry = yaml.safe_load((root / 'manifest.yaml').read_text(encoding='utf-8'))['scenarios']
    sums = dict((name, digest) for digest, name in (line.split() for line in (root / 'SHA256SUMS').read_text().splitlines()))
    if set(registry) != set(PINNED) | {'SCENARIO-FISH-001'}:
        raise ValueError('Scenario registry differs from fixed scenario identities')
    for generation, pins in (('1.0', PINNED), ('2.0', V2_PINNED)):
        for sid, (name, expected) in pins.items():
            actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
            entry = registry[sid]['versions'][generation]
            if actual != expected or entry['sha256'] != expected or sums.get(name) != expected or entry['version'] != generation or entry['path'] != f'scenarios/{name}':
                raise ValueError(f'Scenario integrity mismatch: {sid}/{generation}, file={name}, expected={expected}, actual={actual}; formal run refused')
    fish_name,fish_digest=FISH_PINNED
    fish_entry=registry['SCENARIO-FISH-001']['versions']['1.0']
    actual=hashlib.sha256((root/fish_name).read_bytes()).hexdigest()
    if actual!=fish_digest or sums.get(fish_name)!=fish_digest or fish_entry['sha256']!=fish_digest or fish_entry['version']!='1.0' or fish_entry['path']!='scenarios/fish.md':
        raise ValueError('Scenario integrity mismatch: SCENARIO-FISH-001/1.0')
    if scenario_id=='SCENARIO-FISH-001':
        if version!='1.0':
            raise ValueError(f'Unknown scenario version: {version}')
        return dict(scenario_id=scenario_id,scenario_version=version,scenario_sha256=fish_digest,
                    scenario_file='scenarios/fish.md',text=(root/fish_name).read_text(encoding='utf-8'))
    if scenario_id not in PINNED:
        raise ValueError(f'Unknown scenario: {scenario_id}')
    if version not in ('1.0', '2.0'):
        raise ValueError(f'Unknown scenario version: {version}')
    name, digest = (PINNED if version == '1.0' else V2_PINNED)[scenario_id]
    return dict(scenario_id=scenario_id, scenario_version=version, scenario_sha256=digest, scenario_file=f'scenarios/{name}',
                text=(root / name).read_text(encoding='utf-8'))
