from dataclasses import replace
from http.client import IncompleteRead
from io import BytesIO
import json
import time

import pytest
import yaml

from causal_graph.config import load_llm
from causal_graph.io import read_json
from causal_graph.llm_client import LLMClient
from causal_graph.streaming import read_stream


class StreamResponse(BytesIO):
    status = 200


def events(*chunks, done=True):
    body = ''.join('data: ' + json.dumps(c, ensure_ascii=False) + '\n\n' for c in chunks)
    return (body + ('data: [DONE]\n\n' if done else '')).encode('utf-8')


def test_sse_content_usage_and_original_reasoning(tmp_path, llm, monkeypatch):
    body = events({'model': 'returned-model', 'id': 'response-1', 'choices': [
        {'index': 0, 'delta': {'reasoning_content': 'original reasoning'}, 'finish_reason': None}]},
        {'choices': [{'index': 0, 'delta': {'content': '{"a":'}, 'finish_reason': None}]},
        {'choices': [{'index': 0, 'delta': {'content': '1}'}, 'finish_reason': 'stop'}],
         'usage': {'total_tokens': 15}})
    seen = []
    def respond(request, timeout):
        seen.append(json.loads(request.data))
        return StreamResponse(body)
    monkeypatch.setenv(llm.api_key_env, 'fixture-key')
    monkeypatch.setattr('causal_graph.llm_client.urlopen', respond)
    output = tmp_path / 'call'
    assert LLMClient(replace(llm, stream=True)).complete([], output) == '{"a":1}'
    assert seen[0]['stream'] is True
    assert (output / 'transport_0.response.txt').read_bytes() == body
    assert 'original reasoning' in (output / 'transport_0.response.txt').read_text()
    meta = read_json(output / 'response_metadata.json')
    assert meta['usage']['total_tokens'] == 15 and meta['actual_model'] == 'returned-model'


def test_incomplete_nonstream_retry_preserves_partial_and_secret(tmp_path, llm, monkeypatch):
    key = 'test-only-secret'
    class Broken(StreamResponse):
        def read(self, *args):
            raise IncompleteRead(('partial ' + key).encode())
    good = {'model': llm.model, 'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]}
    replies = iter([Broken(), StreamResponse(json.dumps(good).encode())])
    monkeypatch.setenv(llm.api_key_env, key)
    monkeypatch.setattr('causal_graph.llm_client.urlopen', lambda *a, **k: next(replies))
    monkeypatch.setattr('causal_graph.llm_client.time.sleep', lambda _: None)
    output = tmp_path / 'call'
    assert LLMClient(replace(llm, max_retries=1)).complete([], output) == '{}'
    assert (output / 'transport_0.response.txt').read_text() == 'partial [REDACTED_API_KEY]'
    assert read_json(output / 'transport_0.error.json')['type'] == 'IncompleteRead'
    assert (output / 'transport_1.json').exists()


def test_missing_done_is_not_a_complete_response(tmp_path, llm, monkeypatch):
    body = events({'choices': [{'index': 0, 'delta': {'content': '{}'}, 'finish_reason': 'stop'}]}, done=False)
    calls = []
    def respond(*args, **kwargs):
        calls.append(1)
        return StreamResponse(body)
    monkeypatch.setenv(llm.api_key_env, 'test-only-key')
    monkeypatch.setattr('causal_graph.llm_client.urlopen', respond)
    monkeypatch.setattr('causal_graph.llm_client.time.sleep', lambda _: None)
    output = tmp_path / 'call'
    with pytest.raises(RuntimeError):
        LLMClient(replace(llm, stream=True, max_retries=1)).complete([], output)
    assert len(calls) == 2
    assert (output / 'transport_0.response.txt').read_bytes() == body
    assert not (output / 'response.txt').exists()


def test_stream_deadline(tmp_path):
    with pytest.raises(TimeoutError):
        read_stream(StreamResponse(b''), tmp_path / 'raw.txt', lambda s: s, time.monotonic() - 1)


@pytest.mark.parametrize('stream,options', [('yes', {}), (False, {'include_usage': True}),
                                         (True, {'include_usage': 'yes'})])
def test_invalid_stream_configuration(tmp_path, llm, stream, options):
    profile = llm.summary()
    profile.pop('profile')
    profile.update(stream=stream, extra_body={'stream_options': options})
    file = tmp_path / 'config.yaml'
    file.write_text(yaml.safe_dump({'default_profile': 'a', 'profiles': {'a': profile}}))
    with pytest.raises(ValueError):
        load_llm(file)
