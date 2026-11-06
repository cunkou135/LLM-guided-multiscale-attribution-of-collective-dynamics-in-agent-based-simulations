from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from causal_graph.config import load_llm, load_pipeline


CONFIG = Path(__file__).resolve().parents[1] / 'configs'


def test_profiles_and_missing_key(monkeypatch):
    a, b = load_llm(CONFIG / 'llm.yaml'), load_llm(CONFIG / 'llm.yaml', 'model_b')
    assert a.model != b.model and a.api_key_env != b.api_key_env
    monkeypatch.delenv(a.api_key_env, raising=False)
    with pytest.raises(ValueError, match='Missing API key'):
        a.api_key()
    assert 'api_key' not in a.summary()
    assert load_pipeline(CONFIG / 'pipeline.yaml').execution_mode == 'isolated'


@pytest.mark.parametrize('key,value', [('unknown', 1), ('api_key', 'forbidden'), ('temperature', float('nan')),
                                     ('provider', 'unknown'), ('base_url', 'https://key:secret@example.com/v1'),
                                     ('extra_body', {'model': 'override'}), ('max_tokens', 0), ('max_retries', -1)])
def test_invalid_llm_config(tmp_path, key, value):
    cfg = yaml.safe_load((CONFIG / 'llm.yaml').read_text())
    cfg['profiles']['model_a'][key] = value
    file = tmp_path / 'llm.yaml'
    file.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError):
        load_llm(file)


def test_unknown_profile_and_pipeline_keys(tmp_path):
    with pytest.raises(ValueError, match='Unknown model profile'):
        load_llm(CONFIG / 'llm.yaml', 'absent')
    file = tmp_path / 'pipeline.yaml'
    file.write_text('execution_mode: unsafe\n')
    with pytest.raises(ValueError):
        load_pipeline(file)
