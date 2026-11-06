"""OpenAI-compatible chat transport, raw per-attempt audit, no model fallback."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .io import now, save_json


class LLMClient:
    mode = 'live_api'

    def __init__(self, config):
        self.config = config

    def complete(self, messages, directory):
        directory.mkdir(parents=True, exist_ok=False)
        c = self.config
        payload = {'model': c.model, 'messages': messages, 'max_tokens': c.max_tokens}
        for name in ('temperature', 'top_p', 'reasoning_effort'):
            if getattr(c, name) is not None:
                payload[name] = getattr(c, name)
        if 'max_completion_tokens' in c.extra_body:
            payload.pop('max_tokens')
        payload.update(c.extra_body)
        save_json(directory / 'request.json', {'url': c.base_url.rstrip('/') + '/chat/completions',
                                              'payload': payload, 'config': c.summary(), 'started_at': now()})
        try:
            key = c.api_key()
        except ValueError:
            save_json(directory / 'failure.json', {'error': 'missing_api_key', 'environment_variable': c.api_key_env})
            raise
        # Only the authorization header ever receives the secret. It is never serialized.
        redact = lambda s: s.replace(key, '[REDACTED_API_KEY]')
        for attempt in range(c.max_retries + 1):
            started = time.monotonic()
            raw = ''
            status = None
            try:
                request = Request(c.base_url.rstrip('/') + '/chat/completions',
                                  json.dumps(payload).encode('utf-8'),
                                  {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
                with urlopen(request, timeout=c.timeout) as response:
                    status = response.status
                    raw = response.read().decode('utf-8')
                (directory / f'transport_{attempt}.response.txt').write_text(redact(raw), encoding='utf-8')
                body = json.loads(raw)
                message = body['choices'][0]['message']['content']
                if not isinstance(message, str) or not message.strip():
                    raise ValueError('Provider returned no textual message content')
                metadata = {'actual_model': body.get('model'), 'requested_model': c.model,
                            'usage': body.get('usage'), 'response_id': body.get('id'),
                            'finish_reason': body['choices'][0].get('finish_reason'),
                            'elapsed_seconds': time.monotonic() - started, 'status': status, 'ended_at': now()}
                save_json(directory / f'transport_{attempt}.json', metadata)
                save_json(directory / 'response_metadata.json', metadata)
                (directory / 'response.txt').write_text(redact(message), encoding='utf-8')
                if metadata['finish_reason'] in ('length', 'content_filter'):
                    raise ValueError(f'Incomplete response: {metadata["finish_reason"]}')
                return redact(message)
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                if isinstance(exc, HTTPError):
                    status = exc.code
                    raw = exc.read().decode('utf-8', errors='replace')
                if raw:
                    (directory / f'transport_{attempt}.response.txt').write_text(redact(raw), encoding='utf-8')
                save_json(directory / f'transport_{attempt}.error.json',
                          {'type': type(exc).__name__, 'error': redact(str(exc)), 'status': status,
                           'elapsed_seconds': time.monotonic() - started, 'ended_at': now()})
                retryable = isinstance(exc, (URLError, TimeoutError, OSError))
                if isinstance(exc, HTTPError):
                    retryable = exc.code in (408, 429) or exc.code >= 500
                if attempt == c.max_retries or not retryable:
                    raise RuntimeError(f'LLM request failed; inspect {directory.name} transport audit') from None
                time.sleep(min(2 ** attempt, 8))
