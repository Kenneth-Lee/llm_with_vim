#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import json

from llm_engine import engine


def _prepare_min_config():
    engine._config = {
        "request_template": {"messages": []},
        "default_config": {
            "model": "default",
            "max_tokens": 1024,
            "temperature": 1,
            "connect_timeout": 30,
            "read_timeout": 1800,
            "tools": [],
            "max_tool_rounds": 10,
            "thinking": False,
        },
        "config": {
            "engine_type": "ollama",
            "server_addr": "localhost",
            "model": "default",
        },
        "auth_keys": {},
    }


def test_add_msg_preserves_boundary_whitespace():
    req = {"messages": []}
    content = "  hello\n"
    engine._add_msg(req, "user", content)
    assert req["messages"][0]["content"] == "  hello\n"


def test_stable_json_dumps_deterministic():
    obj = {
        "b": 1,
        "a": {"y": 2, "x": 3},
    }
    s1 = engine._stable_json_dumps(obj)
    s2 = engine._stable_json_dumps(obj)
    assert s1 == s2
    assert s1 == '{"a":{"x":3,"y":2},"b":1}'


def test_payload_hash_deterministic_for_same_input():
    payload = {
        "messages": [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "U"},
        ],
        "stream": True,
        "think": False,
    }
    text1 = engine._stable_json_dumps(payload)
    text2 = engine._stable_json_dumps(payload)
    assert engine._sha256_text(text1) == engine._sha256_text(text2)


def test_parse_input_no_template_mutation_side_effect():
    _prepare_min_config()

    first = "User: A\n"
    second = "User: B\n"

    old_stdin = engine.sys.stdin
    try:
        engine.sys.stdin = io.StringIO(first)
        h1, _ = engine._parse_input()
        assert len(h1["messages"]) == 1

        engine.sys.stdin = io.StringIO(second)
        h2, _ = engine._parse_input()
        assert len(h2["messages"]) == 1
        assert h2["messages"][0]["content"] == "B\n"
    finally:
        engine.sys.stdin = old_stdin


def test_tool_role_encoding_and_decoding_roundtrip():
    payload = engine._format_tool_role_content(
        "read_file",
        {"path": "a.txt"},
        "file-content\n",
        "call_1",
    )
    decoded = engine._decode_tool_role_content(payload)
    assert decoded == "file-content\n"


def test_parse_input_includes_tool_role_message():
    _prepare_min_config()
    raw = (
        'User: hello\n'
        'Tool: {"v":1,"name":"read_file","arguments":{"path":"a.txt"},"result":"abc\\n","id":"call_1"}\n'
        'Assistant: done\n'
    )

    old_stdin = engine.sys.stdin
    try:
        engine.sys.stdin = io.StringIO(raw)
        history, _ = engine._parse_input()
    finally:
        engine.sys.stdin = old_stdin

    assert len(history["messages"]) == 3
    assert history["messages"][1]["role"] == "tool"
    assert history["messages"][1]["content"] == "abc\n"


def test_validate_history_requires_user_message():
    assert engine._validate_history_before_request({'messages': []}) is False
    assert engine._validate_history_before_request({
        'messages': [{'role': 'system', 'content': 'x'}]
    }) is False
    assert engine._validate_history_before_request({
        'messages': [{'role': 'user', 'content': 'x'}]
    }) is True


def test_orphan_lines_are_recorded_in_parse_diagnostics():
    _prepare_min_config()
    raw = (
        '这是无角色文本\n'
        'User: hi\n'
    )

    old_stdin = engine.sys.stdin
    try:
        engine.sys.stdin = io.StringIO(raw)
        history, _ = engine._parse_input()
    finally:
        engine.sys.stdin = old_stdin

    assert len(history['messages']) == 1
    diagnostics = engine._get_parse_diagnostics()
    assert diagnostics['orphan_lines']
    assert diagnostics['orphan_lines'][0][0] == 1
