import pytest

from causal_graph.config import LLMConfig, PipelineConfig
from simulations.common.runner import load, run


@pytest.fixture
def llm():
    return LLMConfig(profile='offline', provider='openai_compatible', base_url='https://api.example.com/v1',
                     model='not-a-real-model', api_key_env='UNSET_TEST_KEY')


@pytest.fixture
def settings():
    return PipelineConfig(generation_attempts=2)


@pytest.fixture(scope='session')
def small_run(tmp_path_factory):
    cfg = load('configs/schelling_standard.yaml')
    cfg['steps'] = 4
    cfg['parameters'].update(width=10, height=10, density=.8, homophily=.8)
    cfg['output']['directory'] = str(tmp_path_factory.mktemp('stage1_schelling'))
    return run(cfg)
