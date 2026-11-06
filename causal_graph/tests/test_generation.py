from dataclasses import replace
from io import BytesIO
import json
from urllib.error import HTTPError, URLError

import pytest

from causal_graph.generation import generate_stage
from causal_graph.io import read_json
from causal_graph.llm_client import LLMClient
from causal_graph.prompts import build_messages
from .fixtures import OfflineClient


def test_prompt_boundary(settings):
    context = {'data_schema': {'schema_version':'2.0','tables':{}}, 'phenomena': [], 'indicators': [], 'codes': ['SOURCE_SECRET'],
               'field_catalog': 'CATALOG_SECRET', 'data': 'TRAJECTORY_SECRET'}
    for stage in ('phenomena', 'indicators', 'codes', 'edges_upward', 'edges_downward', 'edges_intrascale'):
        raw = json.dumps(build_messages(stage, 'ONLY CURRENT FIXED SCENARIO', context, settings))
        assert 'ONLY CURRENT FIXED SCENARIO' in raw
        assert not any(secret in raw for secret in ('SOURCE_SECRET', 'CATALOG_SECRET', 'TRAJECTORY_SECRET'))


def test_generation_cache_and_raw_response(tmp_path, settings):
    client = OfflineClient()
    first, _ = generate_stage('phenomena', 'fixed scenario', {}, settings, client, tmp_path)
    assert generate_stage('phenomena', 'fixed scenario', {}, settings, client, tmp_path)[0] == first
    assert len(client.calls) == 1
    assert list(tmp_path.glob('generation/phenomena/attempt_*/response.txt'))
    with pytest.raises(ValueError, match='prompt mismatch'):
        generate_stage('phenomena', 'different scenario', {}, settings, client, tmp_path)


def test_checkpoint_schema_identity_even_when_not_in_first_prompt(tmp_path, settings):
    client = OfflineClient()
    first = {'data_schema': {'schema_version': '2.0', 'tables': {}}}
    generate_stage('phenomena', 'fixed', first, settings, client, tmp_path)
    changed = {'data_schema': {'schema_version': '2.0', 'tables': {'new_table': {}}}}
    with pytest.raises(ValueError, match='checkpoint prompt mismatch'):
        generate_stage('phenomena', 'fixed', changed, settings, client, tmp_path)


def test_invalid_json_retries_same_prompt(tmp_path, settings):
    class Broken(OfflineClient):
        def complete(self, messages, directory):
            directory.mkdir()
            self.calls.append(messages)
            return 'not JSON'
    client = Broken()
    with pytest.raises(ValueError, match='structural validation failed'):
        generate_stage('phenomena', 'fixed', {}, settings, client, tmp_path)
    assert len(client.calls) == settings.generation_attempts
    assert client.calls[0] == client.calls[1]
    assert len(list(tmp_path.glob('generation/phenomena/attempt_*/validation.json'))) == 2


class Response:
    status = 200
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self):
        return json.dumps(self.body).encode()


def test_transport_metadata_and_secret_redaction(tmp_path, llm, monkeypatch):
    key = 'unit-test-secret-not-a-real-key'
    monkeypatch.setenv(llm.api_key_env, key)
    requests = []
    def fake(request, timeout):
        requests.append(json.loads(request.data))
        assert request.headers['Authorization'] == 'Bearer ' + key
        return Response({'model': 'returned-model-id', 'usage': {'total_tokens': 9}, 'id': 'response-id',
                         'choices': [{'message': {'content': '{"note":"' + key + '"}'}, 'finish_reason': 'stop'}]})
    monkeypatch.setattr('causal_graph.llm_client.urlopen', fake)
    LLMClient(llm).complete([{'role': 'user', 'content': 'scenario'}], tmp_path / 'transport')
    meta = read_json(tmp_path / 'transport/response_metadata.json')
    assert meta['actual_model'] == 'returned-model-id' and meta['usage']['total_tokens'] == 9
    assert requests[0]['model'] == llm.model
    assert all(key not in p.read_text() for p in tmp_path.rglob('*') if p.is_file())


def test_no_key_is_local_failure(tmp_path, llm, monkeypatch):
    monkeypatch.delenv(llm.api_key_env, raising=False)
    with pytest.raises(ValueError, match='Missing API key'):
        LLMClient(llm).complete([], tmp_path / 'transport')
    assert (tmp_path / 'transport/failure.json').is_file()


@pytest.mark.parametrize('status,calls', [(400, 1), (429, 2), (500, 2)])
def test_transport_retry_policy(tmp_path, llm, monkeypatch, status, calls):
    monkeypatch.setenv(llm.api_key_env, 'test-only-key')
    seen = []
    def fail(*args, **kwargs):
        seen.append(1)
        raise HTTPError(llm.base_url, status, 'provider error', {}, BytesIO(b'unsupported parameter'))
    monkeypatch.setattr('causal_graph.llm_client.urlopen', fail)
    monkeypatch.setattr('causal_graph.llm_client.time.sleep', lambda _: None)
    with pytest.raises(RuntimeError):
        LLMClient(replace(llm, max_retries=1)).complete([], tmp_path / 'transport')
    assert len(seen) == calls
