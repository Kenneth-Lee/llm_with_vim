# -*- coding: utf-8 -*-
"""Provider spec loading, validation, and runtime resolution for ContextForge."""

from __future__ import print_function

import copy
import json
import os
import re
import sys

_APP_NAME = 'contextforge'
_LEGACY_APP_NAME = 'llm_engine'
_PACKAGE_DIR = os.path.dirname(__file__)
_BUILTIN_PROVIDER_DIR = os.path.join(_PACKAGE_DIR, 'providers')

_REQUIRED_SPEC_KEYS = (
    'schema_version',
    'spec_version',
    'id',
    'protocol',
    'defaults',
    'endpoint',
    'auth',
    'features',
    'request_mapping',
    'response_mapping',
)


def _is_missing(value):
    return value is None or value == '' or value == 'default'


def load_json_file(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, OSError, json.JSONDecodeError):
        return None


def deep_merge(base, override):
    """Deep merge override into base and return base."""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override

    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def get_config_root():
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
        return os.path.join(base, _APP_NAME)

    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, _APP_NAME)


def get_legacy_config_root():
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
        return os.path.join(base, _LEGACY_APP_NAME)

    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, _LEGACY_APP_NAME)


def get_user_config_path():
    env_path = os.environ.get('LLM_ENGINE_CONFIG')
    if env_path:
        return os.path.expanduser(env_path)
    return os.path.join(get_config_root(), 'config.json')


def get_legacy_user_config_path():
    return os.path.join(get_legacy_config_root(), 'llm_engine.json')


def get_builtin_provider_dir():
    return _BUILTIN_PROVIDER_DIR


def get_user_provider_dir():
    return os.path.join(get_config_root(), 'providers')


def get_provider_spec_path(provider_id, user=False):
    base_dir = get_user_provider_dir() if user else get_builtin_provider_dir()
    return os.path.join(base_dir, '%s.json' % provider_id)


def validate_provider_spec(spec):
    errors = []
    if not isinstance(spec, dict):
        return ['provider spec must be a JSON object']

    for key in _REQUIRED_SPEC_KEYS:
        if key not in spec:
            errors.append('missing required key: %s' % key)

    schema_version = spec.get('schema_version')
    if schema_version != 1:
        errors.append('schema_version must be 1')

    if not isinstance(spec.get('defaults', {}), dict):
        errors.append('defaults must be an object')
    if not isinstance(spec.get('endpoint', {}), dict):
        errors.append('endpoint must be an object')
    if not isinstance(spec.get('auth', {}), dict):
        errors.append('auth must be an object')
    if not isinstance(spec.get('features', {}), dict):
        errors.append('features must be an object')
    if not isinstance(spec.get('request_mapping', {}), dict):
        errors.append('request_mapping must be an object')
    if not isinstance(spec.get('response_mapping', {}), dict):
        errors.append('response_mapping must be an object')

    return errors


def load_provider_spec(provider_id, fallback_provider_id='openai_compat'):
    provider_id = provider_id or fallback_provider_id

    builtin = load_json_file(get_provider_spec_path(provider_id, user=False))
    user = load_json_file(get_provider_spec_path(provider_id, user=True))

    if builtin is None and user is None and provider_id != fallback_provider_id:
        builtin = load_json_file(get_provider_spec_path(fallback_provider_id, user=False))
        user = load_json_file(get_provider_spec_path(fallback_provider_id, user=True))
        provider_id = fallback_provider_id

    if builtin is None and user is None:
        return None

    if builtin is None:
        spec = copy.deepcopy(user)
    elif user is None:
        spec = copy.deepcopy(builtin)
    else:
        spec = deep_merge(copy.deepcopy(builtin), user)

    errors = validate_provider_spec(spec)
    if errors:
        raise ValueError('Invalid provider spec for %s: %s' % (provider_id, '; '.join(errors)))

    return spec


def list_builtin_provider_ids():
    if not os.path.isdir(get_builtin_provider_dir()):
        return []
    result = []
    for name in os.listdir(get_builtin_provider_dir()):
        if name.endswith('.json'):
            result.append(name[:-5])
    return sorted(result)


def list_provider_specs():
    """枚举全部 provider 描述：内置目录 + 用户目录（同名时用户文件深合并
    覆盖内置），返回按 id 排序的 spec 列表。供环境查询（TELLME）使用。"""
    specs = {}
    for provider_id in list_builtin_provider_ids():
        spec = load_provider_spec(provider_id)
        if spec:
            specs[provider_id] = spec
    user_dir = get_user_provider_dir()
    if os.path.isdir(user_dir):
        for name in sorted(os.listdir(user_dir)):
            if not name.endswith('.json'):
                continue
            provider_id = name[:-5]
            if provider_id in specs:
                continue  # 同名用户文件已在 load_provider_spec 中合并
            spec = load_json_file(os.path.join(user_dir, name))
            if not spec:
                continue
            errors = validate_provider_spec(spec)
            if errors:
                sys.stderr.write('[provider] %s ignored: %s\n'
                                 % (name, '; '.join(errors)))
                continue
            specs[provider_id] = spec
    return [specs[provider_id] for provider_id in sorted(specs)]


def _resolve_alias(value, aliases):
    if value in aliases:
        return aliases[value]
    return value


def apply_provider_defaults(spec, config):
    runtime = copy.deepcopy(config)
    defaults = spec.get('defaults', {})
    aliases = spec.get('aliases', {})
    model_aliases = aliases.get('model', {})
    server_aliases = aliases.get('server', {})
    endpoint = spec.get('endpoint', {})

    for key, value in defaults.items():
        if _is_missing(runtime.get(key)):
            runtime[key] = value

    if _is_missing(runtime.get('server_addr')):
        runtime['server_addr'] = endpoint.get('default_host', 'localhost')

    if not _is_missing(runtime.get('server_addr')):
        runtime['server_addr'] = _resolve_alias(runtime['server_addr'], server_aliases)

    if not _is_missing(runtime.get('model')):
        runtime['model'] = _resolve_alias(runtime['model'], model_aliases)
    if _is_missing(runtime.get('model')):
        runtime['model'] = defaults.get('model', runtime.get('model'))

    return runtime


def _split_host_port(raw_addr):
    """Split 'host:port' into (host, port). Supports '[v6-addr]:port' literals."""
    if not raw_addr or not isinstance(raw_addr, str):
        return raw_addr, None
    addr = raw_addr.strip()
    if addr.startswith('['):
        # IPv6 literal like [::1]:8080
        end = addr.find(']')
        if end == -1:
            return addr, None
        host = addr[:end + 1]
        rest = addr[end + 1:]
        if rest.startswith(':') and rest[1:].isdigit():
            return host, int(rest[1:])
        return host, None
    if addr.count(':') == 1:
        host, _, port_str = addr.partition(':')
        if port_str.isdigit():
            return host, int(port_str)
    return addr, None


def _format_endpoint_url(template, runtime_config, endpoint):
    """Format an endpoint template against runtime config.

    - If the template carries a ``{port}`` placeholder, ``server_addr`` may
      still embed a port (``host:port``); it is split so the port is not
      duplicated. Port priority: server_port config > port embedded in
      server_addr > spec default_port.
    - If the template has no ``{port}`` placeholder, the raw server_addr is
      passed through unchanged so ``host:port`` keeps working (legacy
      behaviour for {server_addr}-style templates).
    """
    raw_addr = runtime_config.get('server_addr') or endpoint.get('default_host', 'localhost')

    if '{port}' not in template:
        values = {'host': raw_addr, 'server_addr': raw_addr, 'port': ''}
    else:
        addr_host, addr_port = _split_host_port(raw_addr)
        port = runtime_config.get('server_port') or addr_port or endpoint.get('default_port') or ''
        values = {'host': addr_host, 'server_addr': addr_host, 'port': port}

    try:
        url = template.format(**values)
    except Exception:
        return template

    if '{port}' in template and not values['port']:
        # No port resolved but the template requested one: drop the dangling ':0'
        url = re.sub(r'(://[^/:?#]+):(?:0)?(?=[/?#]|$)', r'\1', url)
    return url


def build_api_url(spec, runtime_config):
    endpoint = spec.get('endpoint', {})
    template = endpoint.get('template', '')
    return _format_endpoint_url(template, runtime_config, endpoint)


def build_model_query_url(spec, runtime_config):
    model_query = spec.get('model_query', {})
    template = model_query.get('url_template', '')
    if not template:
        return None
    return _format_endpoint_url(template, runtime_config, spec.get('endpoint', {}))


def build_auth_headers(spec, provider_id, runtime_config, global_config, session_config=None):
    headers = {'Content-Type': 'application/json'}
    auth_value = None
    if session_config:
        auth_value = session_config.get('auth')
    if not auth_value:
        auth_value = runtime_config.get('auth')
    if not auth_value:
        auth_keys = global_config.get('auth_keys', {})
        auth_value = auth_keys.get(provider_id, '')

    if not auth_value:
        return headers

    auth_cfg = spec.get('auth', {})
    if auth_cfg.get('type') == 'header':
        header_name = auth_cfg.get('header_name', 'Authorization')
        headers[header_name] = auth_value
    return headers


def resolve_provider_runtime(provider_id, base_config, global_config, session_config=None):
    spec = load_provider_spec(provider_id)
    if spec is None:
        raise ValueError('Unknown provider: %s' % provider_id)

    runtime_config = apply_provider_defaults(spec, base_config)

    # Session (per-file Configure line) server settings must affect the URL,
    # not only authentication headers.
    if session_config:
        session_server = session_config.get('server_addr')
        session_port = session_config.get('server_port')
        if not _is_missing(session_server):
            runtime_config['server_addr'] = session_server
        if session_port:
            runtime_config['server_port'] = session_port
        # Re-apply defaults so aliases in session values get resolved too.
        runtime_config = apply_provider_defaults(spec, runtime_config)
    protocol = spec.get('protocol', 'openai_compat')
    response_mode = spec.get('response_mapping', {}).get('mode', 'sse_openai_delta')
    api_url = build_api_url(spec, runtime_config)
    model_query_url = build_model_query_url(spec, runtime_config)
    headers = build_auth_headers(spec, provider_id, runtime_config, global_config, session_config=session_config)

    return {
        'spec': spec,
        'provider_id': spec.get('id', provider_id),
        'protocol': protocol,
        'response_mode': response_mode,
        'runtime_config': runtime_config,
        'api_url': api_url,
        'model_query_url': model_query_url,
        'headers': headers,
    }
