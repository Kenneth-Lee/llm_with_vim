#!/usr/bin/env python3
"""测试 Ollama 图像请求格式"""

import os
import sys
import json

# 将目录添加到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入引擎（不使用 __main__ 部分）
exec(open('llm_engine.py').read())

# 捕获转换后的消息
class MockHistory:
    def __init__(self):
        self.data = {'messages': []}
    def __getitem__(self, key):
        return self.data.get(key)
    def __setitem__(self, key, value):
        self.data[key] = value

# 测试：模拟 user 配置要求 llava
test_input = '''Configure:  {'engine_type': 'ollama', 'model': 'llava', 'keep_alive': 3600}
System: You are a vision assistant.
User: What do you see?
$$/tmp/test_image.png$$
'''

import io
sys.stdin = io.StringIO(test_input)
os.environ['LLM_FILE_DIR'] = '/tmp'

_load_config()
history, uc = _parse_input()

print("=== 原始解析的消息 ===")
print(json.dumps(history, indent=2, ensure_ascii=False)[:800])

# 模拟转换
if 'messages' in history:
    print("\n=== 转换后的 Ollama 格式 ===")
    
    # 手动执行转换逻辑
    def test_convert(messages, engine_type):
        converted = []
        for msg in messages:
            if msg.get('role') == 'user' and 'images' in msg and msg['images']:
                if engine_type == 'ollama':
                    converted.append({
                        'role': msg['role'],
                        'content': msg.get('content', ''),
                        'images': msg['images'][:50] + '...'  # 截断显示
                    })
                else:
                    converted.append({k: v for k, v in msg.items() if k != 'images'})
            else:
                converted.append(msg)
        return converted
    
    converted = test_convert(history['messages'], 'ollama')
    print(json.dumps(converted, indent=2, ensure_ascii=False))
    
print("\n=== 检查要点 ===")
print("1. User 消息是否有 'images' 字段?", 'images' in history.get('messages', [{}])[1] if len(history.get('messages', [])) > 1 else False)
print("2. 图片数量:", len(history.get('messages', [{}])[1].get('images', [])) if len(history.get('messages', [])) > 1 else 0)
