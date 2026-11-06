"""Read OpenAI-compatible SSE while preserving partial responses on disk."""
import json
import time
from http.client import IncompleteRead


class StreamInterrupted(ConnectionError):
    """A response ended before its explicit finish marker."""


def read_stream(response, path, redact, deadline):
    content = []
    metadata = {'model': None, 'usage': None, 'id': None}
    finish = None
    done = False
    event = []

    def consume(lines):
        nonlocal finish, done
        if not lines:
            return
        payload = '\n'.join(lines)
        if payload.strip() == '[DONE]':
            done = True
            return
        chunk = json.loads(payload)
        if 'error' in chunk:
            raise ValueError('Provider sent an error event; inspect raw stream')
        for key in ('model', 'usage', 'id'):
            if chunk.get(key) is not None:
                metadata[key] = chunk[key]
        for choice in chunk.get('choices', []):
            if choice.get('index', 0) != 0:
                raise ValueError('Unexpected multiple completion choices')
            delta = choice.get('delta', {})
            if delta.get('content') is not None:
                if not isinstance(delta['content'], str):
                    raise ValueError('Stream content delta must be text')
                content.append(delta['content'])
            if choice.get('finish_reason') is not None:
                finish = choice['finish_reason']

    with path.open('w', encoding='utf-8', newline='') as raw:
        while not done:
            if time.monotonic() > deadline:
                raise TimeoutError('Streaming request exceeded configured timeout')
            try:
                line = response.readline()
            except IncompleteRead as exc:
                raw.write(redact(exc.partial.decode('utf-8', errors='replace')))
                raw.flush()
                raise
            if not line:
                if event:
                    consume(event)
                break
            text = line.decode('utf-8')
            raw.write(redact(text))
            raw.flush()
            stripped = text.rstrip('\r\n')
            if not stripped:
                consume(event)
                event = []
            elif stripped.startswith('data:'):
                value = stripped[5:]
                event.append(value[1:] if value.startswith(' ') else value)
            # SSE comments, event names and keepalive lines are kept in raw audit.
    if not done or finish is None:
        raise StreamInterrupted('Stream ended without [DONE] and a finish_reason')
    return {**metadata, 'choices': [{'message': {'content': ''.join(content)}, 'finish_reason': finish}]}
