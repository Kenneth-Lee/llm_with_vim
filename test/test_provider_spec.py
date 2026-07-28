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
