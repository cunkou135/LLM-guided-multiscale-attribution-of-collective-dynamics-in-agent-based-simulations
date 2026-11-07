"""Strict, credential-free YAML configuration."""
from dataclasses import asdict, dataclass, field
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

import yaml


def _load(path):
    value = yaml.safe_load(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('YAML must contain a mapping')
    return value


def _keys(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError(f'Invalid configuration keys; allowed={sorted(allowed)}, required={sorted(required)}')


def _number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


@dataclass(frozen=True)
class LLMConfig:
    profile: str
    provider: str
    base_url: str
    model: str
    api_key_env: str
    temperature: float | None = 0.0
    top_p: float | None = None
    max_tokens: int = 8192
    timeout: float = 120
    max_retries: int = 3
    reasoning_effort: str | None = None
    extra_body: dict = field(default_factory=dict)
    stream: bool = False

    def summary(self):
        return asdict(self)

    def api_key(self):
        value = os.environ.get(self.api_key_env)
        if not value:
            raise ValueError(f'Missing API key environment variable: {self.api_key_env}')
        return value


def load_llm(path, profile=None):
    root = _load(path)
    _keys(root, {'default_profile', 'profiles'}, {'default_profile', 'profiles'})
    if not isinstance(root['profiles'], dict):
        raise ValueError('profiles must be a mapping')
    profile = profile or root['default_profile']
    if not isinstance(profile, str) or profile not in root['profiles']:
        raise ValueError(f'Unknown model profile: {profile}')
    cfg = root['profiles'][profile]
    fields = set(LLMConfig.__dataclass_fields__) - {'profile'}
    _keys(cfg, fields, {'provider', 'base_url', 'model', 'api_key_env'})
    result = LLMConfig(profile=profile, **cfg)
    if result.provider != 'openai_compatible':
        raise ValueError('Unsupported provider; configure openai_compatible explicitly')
    for name in ('base_url', 'model', 'api_key_env'):
        if not isinstance(getattr(result, name), str) or not getattr(result, name).strip():
            raise ValueError(f'{name} must be a nonempty string')
    url = urlsplit(result.base_url)
    if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('base_url requires an HTTP(S) URL without credentials, query or fragment')
    if result.temperature is not None and not _number(result.temperature, 0, 2):
        raise ValueError('temperature must be null or within [0, 2]')
    if result.top_p is not None and not _number(result.top_p, 0, 1):
        raise ValueError('top_p must be null or within [0, 1]')
    if type(result.max_tokens) is not int or result.max_tokens < 1:
        raise ValueError('max_tokens must be a positive integer')
    if not _number(result.timeout, .01, 3600) or type(result.max_retries) is not int or not 0 <= result.max_retries <= 10:
        raise ValueError('Invalid timeout or max_retries')
    if result.reasoning_effort is not None and not isinstance(result.reasoning_effort, str):
        raise ValueError('reasoning_effort must be a string or null')
    if type(result.stream) is not bool:
        raise ValueError('stream must be a boolean')
    # These are explicit adapters, not arbitrary request overrides or secret headers.
    _keys(result.extra_body, {'seed', 'response_format', 'max_completion_tokens',
                             'verbosity', 'chat_template_kwargs', 'enable_thinking', 'stream_options'})
    if 'stream_options' in result.extra_body:
        _keys(result.extra_body['stream_options'], {'include_usage'})
        if not result.stream or any(type(v) is not bool for v in result.extra_body['stream_options'].values()):
            raise ValueError('stream_options requires stream=true and boolean include_usage')
    if 'max_completion_tokens' in result.extra_body and (
            type(result.extra_body['max_completion_tokens']) is not int or result.extra_body['max_completion_tokens'] < 1):
        raise ValueError('max_completion_tokens must be a positive integer')
    return result


@dataclass(frozen=True)
class PipelineConfig:
    max_phenomena: int = 6
    max_indicators: int = 36
    max_edges: int = 144
    generation_attempts: int = 2
    execution_mode: str = 'isolated'
    image: str = 'abms-indicator:1'
    indicator_timeout: int = 30
    min_observations: int = 3
    missing_fraction_warning: float = .2
    code_batch_size: int = 0
    min_indicators_per_scale: int = 0
    target_indicators_per_scale: int = 0
    require_analysis_contract: bool = False
    execution_step_batch_size: int = 0

    def summary(self):
        return asdict(self)


def load_pipeline(path):
    cfg = _load(path)
    _keys(cfg, PipelineConfig.__dataclass_fields__)
    result = PipelineConfig(**cfg)
    for name in ('max_phenomena', 'max_indicators', 'max_edges', 'generation_attempts', 'min_observations'):
        if type(getattr(result, name)) is not int or getattr(result, name) < 1:
            raise ValueError(f'{name} must be a positive integer')
    if result.execution_mode not in ('isolated', 'trusted_reviewed'):
        raise ValueError('execution_mode must be isolated or trusted_reviewed')
    if type(result.code_batch_size) is not int or result.code_batch_size < 0:
        raise ValueError('code_batch_size must be a nonnegative integer; zero means a single call')
    if any(type(getattr(result, key)) is not int or getattr(result, key) < 0 for key in
           ('min_indicators_per_scale', 'target_indicators_per_scale')):
        raise ValueError('Scale minimum and target must be nonnegative integers')
    if result.target_indicators_per_scale < result.min_indicators_per_scale or 3 * result.target_indicators_per_scale > result.max_indicators:
        raise ValueError('Require min_per_scale <= target_per_scale and 3*target <= max_indicators')
    if type(result.require_analysis_contract) is not bool:
        raise ValueError('require_analysis_contract must be boolean')
    if type(result.execution_step_batch_size) is not int or result.execution_step_batch_size < 0:
        raise ValueError('execution_step_batch_size must be a nonnegative integer')
    if type(result.indicator_timeout) is not int or not 1 <= result.indicator_timeout <= 300:
        raise ValueError('indicator_timeout must be within [1, 300]')
    if not _number(result.missing_fraction_warning, 0, 1):
        raise ValueError('missing_fraction_warning must be within [0, 1]')
    if not isinstance(result.image, str) or not result.image:
        raise ValueError('image must be nonempty')
    return result
