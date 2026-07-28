#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from llm_engine.provider_spec import (
    build_api_url,
    build_model_query_url,
    get_config_root,
    get_user_config_path,
    load_provider_spec,
    resolve_provider_runtime,
)
from llm_engine.engine import _is_model_not_found_error
from llm_engine.tools import get_unknown_tool_names


def test_builtin_provider_spec_loads():
    spec = load_provider_spec('ollama')
    assert spec['id'] == 'ollama'
    assert spec['defaults']['model']
    assert spec['endpoint']['template']


def test_config_root_uses_contextforge_name(monkeypatch):
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    monkeypatch.setenv('HOME', '/tmp/fake-home')
    root = get_config_root()
    assert root.endswith(os.path.join('.config', 'contextforge'))
    assert get_user_config_path().endswith(os.path.join('contextforge', 'config.json'))


def test_runtime_resolution_uses_spec_defaults():
    runtime = resolve_provider_runtime('ollama', {'model': 'default'}, {'auth_keys': {}})
    assert runtime['provider_id'] == 'ollama'
    assert runtime['runtime_config']['model'] == 'qwen2.5:0.5b'
    assert runtime['api_url'].endswith('/api/chat')
    assert runtime['model_query_url'].endswith('/api/tags')


def test_api_and_model_query_url_helpers():
    spec = load_provider_spec('openai_compat')
    runtime = {'server_addr': 'localhost', 'server_port': 80}
    assert build_api_url(spec, runtime).endswith('/v1/chat/completions')
    assert build_model_query_url(spec, runtime).endswith('/v1/models')


def test_unknown_provider_falls_back_to_openai_compat():
    runtime = resolve_provider_runtime('unknown_provider_name', {'model': 'default'}, {'auth_keys': {}})
    assert runtime['provider_id'] == 'openai_compat'
    assert runtime['response_mode'] == 'sse_openai_delta'


def test_stream_default_from_provider_spec():
    runtime = resolve_provider_runtime('llama', {'stream': 'default'}, {'auth_keys': {}})
    assert runtime['runtime_config']['stream'] is False


def test_unknown_tool_names_are_detected():
    unknown = get_unknown_tool_names(['ok', 'bash', 'read', 'missing'])
    assert unknown == ['ok', 'missing']


def test_model_not_found_error_detection():
    assert _is_model_not_found_error('model not found: glm-5.2:cloud') is True
    assert _is_model_not_found_error('Error: failed to find model foo') is True
    assert _is_model_not_found_error('pull model manifest: try pulling it first') is True
    assert _is_model_not_found_error('connection refused') is False
