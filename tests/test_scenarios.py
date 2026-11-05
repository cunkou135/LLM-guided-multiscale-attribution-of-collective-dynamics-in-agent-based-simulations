import shutil
import pytest
from scenarios.protocol import ROOT, load_scenario


@pytest.mark.parametrize('sid', ['SCENARIO-SCHELLING-001', 'SCENARIO-COVASIM-001'])
def test_original_scenarios(sid):
    scenario = load_scenario(sid)
    assert scenario['scenario_version'] == '1.0'
    assert scenario['text'].startswith('#### 城市')
    assert '以上为想定正文结束' not in scenario['text']


def test_tampering_refused_even_when_other_scenario_requested(tmp_path):
    for name in ('manifest.yaml', 'SHA256SUMS', 'schelling.md', 'covasim.md'):
        shutil.copyfile(ROOT / name, tmp_path / name)
    with (tmp_path / 'covasim.md').open('a', encoding='utf-8') as stream:
        stream.write('changed')
    with pytest.raises(ValueError, match='formal run refused'):
        load_scenario('SCENARIO-SCHELLING-001', tmp_path)


def test_run_records_fixed_scenario(tmp_path):
    import json
    from simulations.common.runner import load, run
    from simulations.common.trajectory_api import Trajectory
    config = load('configs/schelling.yaml')
    config['steps'] = 1
    config['output']['directory'] = str(tmp_path)
    out = run(config)
    manifest = json.loads((out / 'manifest.json').read_text())
    scenario = load_scenario(config['scenario_id'])
    for field in ('scenario_id', 'scenario_version', 'scenario_sha256'):
        assert manifest[field] == scenario[field]
        assert Trajectory(out).read('agent_states')[field].unique().tolist() == [scenario[field]]
    assert (out / 'scenario.md').read_bytes() == (ROOT / 'schelling.md').read_bytes()
