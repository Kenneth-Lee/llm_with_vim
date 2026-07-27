#!/usr/bin/env python3
"""测试 Ollama 图像请求格式"""

import io

import llm_engine.engine as engine


def _convert_preview(messages, engine_type):
    """模拟请求前转换的关键逻辑（测试用途）。"""
    converted = []
    for msg in messages:
        if msg.get('role') == 'user' and 'images' in msg and msg['images']:
            if engine_type == 'ollama':
                converted.append({
                    'role': msg['role'],
                    'content': msg.get('content', ''),
                    'images': msg['images'],
                })
            else:
                converted.append({k: v for k, v in msg.items() if k != 'images'})
        else:
            converted.append(msg)
    return converted


def test_ollama_image_parse_and_convert(tmp_path, monkeypatch):
    # 1x1 PNG
    png_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\x89\x1f\x0f\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    image_path = tmp_path / 'test_image.png'
    image_path.write_bytes(png_bytes)

    raw = (
        "Configure:  {'engine_type': 'ollama', 'model': 'llava', 'keep_alive': 3600}\n"
        "System: You are a vision assistant.\n"
        "User: What do you see?\n"
        "$$test_image.png$$\n"
    )

    engine._load_config()
    monkeypatch.setenv('LLM_FILE_DIR', str(tmp_path))
    monkeypatch.setattr(engine.sys, 'stdin', io.StringIO(raw))

    history, _ = engine._parse_input()

    assert 'messages' in history
    assert len(history['messages']) >= 2

    user_msg = history['messages'][1]
    assert user_msg['role'] == 'user'
    assert 'images' in user_msg
    assert len(user_msg['images']) == 1
    assert isinstance(user_msg['images'][0], str)
    assert len(user_msg['images'][0]) > 10

    converted = _convert_preview(history['messages'], 'ollama')
    converted_user = converted[1]
    assert converted_user['role'] == 'user'
    assert 'images' in converted_user
    assert len(converted_user['images']) == 1
