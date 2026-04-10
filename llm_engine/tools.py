# -*- coding: utf-8 -*-
"""
LLM Engine Tools - 工具定义与执行

工具的 JSON 定义存放在 tool_definitions.json 中，
本模块负责加载定义、分发执行。
"""

import os
import sys
import json
import re
import base64
import subprocess


MAX_OUTPUT_SIZE = 100000

# 从 JSON 文件加载工具定义
_DEFINITIONS_FILE = os.path.join(os.path.dirname(__file__), 'tool_definitions.json')

def _load_definitions():
    with open(_DEFINITIONS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

TOOL_REGISTRY = _load_definitions()

# function_name -> executor 的映射表
_EXECUTORS = {}


def _register(func_name):
    """装饰器：注册工具执行函数"""
    def decorator(fn):
        _EXECUTORS[func_name] = fn
        return fn
    return decorator


def get_tool_definitions(tool_names):
    """根据工具名列表返回 OpenAI 格式的工具定义"""
    tools = []
    for name in tool_names:
        if name in TOOL_REGISTRY:
            tools.append(TOOL_REGISTRY[name])
    return tools


def execute_tool(func_name, arguments, base_dir=''):
    """执行工具并返回结果字符串"""
    executor = _EXECUTORS.get(func_name)
    if executor:
        return executor(arguments, base_dir)
    return "Error: unknown tool function '%s'" % func_name


def _resolve_path(path, base_dir):
    """解析路径：展开 ~ ，相对路径基于 base_dir"""
    if not path:
        return ''
    path = os.path.expanduser(path)
    if not os.path.isabs(path) and base_dir:
        path = os.path.join(base_dir, path)
    return os.path.normpath(path)


def _truncate(text, limit=MAX_OUTPUT_SIZE):
    if len(text) > limit:
        return text[:limit] + '\n... (truncated, total %d chars)' % len(text)
    return text


# ==================== 工具执行器 ====================

@_register('read_file')
def _execute_read(arguments, base_dir):
    """读取文件内容"""
    path = arguments.get('path', '')
    if not path:
        return "Error: 'path' argument is required"
    path = _resolve_path(path, base_dir)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return _truncate(content)
    except Exception as e:
        return "Error reading file: %s" % e


@_register('write_file')
def _execute_write(arguments, base_dir):
    """写入文件内容"""
    path = arguments.get('path', '')
    content = arguments.get('content', '')
    if not path:
        return "Error: 'path' argument is required"
    path = _resolve_path(path, base_dir)
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return "Successfully wrote %d chars to %s" % (len(content), path)
    except Exception as e:
        return "Error writing file: %s" % e


@_register('edit_file')
def _execute_edit(arguments, base_dir):
    """精确字符串替换编辑"""
    path = arguments.get('path', '')
    old_string = arguments.get('old_string', '')
    new_string = arguments.get('new_string', '')
    if not path:
        return "Error: 'path' argument is required"
    if not old_string:
        return "Error: 'old_string' argument is required"
    path = _resolve_path(path, base_dir)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        count = content.count(old_string)
        if count == 0:
            return "Error: old_string not found in %s" % path
        if count > 1:
            return "Error: old_string found %d times in %s (must be exactly 1)" % (count, path)
        new_content = content.replace(old_string, new_string, 1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return "Successfully edited %s" % path
    except Exception as e:
        return "Error editing file: %s" % e


@_register('bash')
def _execute_bash(arguments, base_dir):
    """执行 bash 命令"""
    command = arguments.get('command', '')
    if not command:
        return "Error: 'command' argument is required"
    try:
        result = subprocess.run(
            ['bash', '-c', command],
            capture_output=True, text=True,
            timeout=30,
            cwd=base_dir or None
        )
        output = ''
        if result.stdout:
            output += result.stdout
        if result.stderr:
            if output:
                output += '\n'
            output += result.stderr
        if not output:
            output = '(exit code %d)' % result.returncode
        return _truncate(output)
    except subprocess.TimeoutExpired:
        return 'Error: command timed out (30s limit)'
    except Exception as e:
        return "Error executing command: %s" % e


@_register('grep_search')
def _execute_search(arguments, base_dir):
    """在文件中搜索文本模式"""
    pattern = arguments.get('pattern', '')
    if not pattern:
        return "Error: 'pattern' argument is required"
    path = arguments.get('path', '') or base_dir or '.'
    path = _resolve_path(path, base_dir)
    include = arguments.get('include', '')

    cmd = ['grep', '-rn', '-E', '--color=never', pattern]
    if include:
        cmd.extend(['--include', include])
    cmd.append(path)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        output = result.stdout or ''
        if result.returncode == 1 and not output:
            return "No matches found for pattern: %s" % pattern
        if result.stderr:
            output += '\n' + result.stderr
        return _truncate(output)
    except subprocess.TimeoutExpired:
        return 'Error: search timed out (30s limit)'
    except Exception as e:
        return "Error searching: %s" % e


@_register('list_dir')
def _execute_list_dir(arguments, base_dir):
    """列出目录内容"""
    path = arguments.get('path', '') or base_dir or '.'
    path = _resolve_path(path, base_dir)
    try:
        entries = sorted(os.listdir(path))
        result_lines = []
        for entry in entries:
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                result_lines.append(entry + '/')
            else:
                result_lines.append(entry)
        return '\n'.join(result_lines) if result_lines else '(empty directory)'
    except Exception as e:
        return "Error listing directory: %s" % e


@_register('python')
def _execute_python(arguments, base_dir):
    """执行 Python 代码"""
    code = arguments.get('code', '')
    if not code:
        return "Error: 'code' argument is required"
    try:
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True, text=True,
            timeout=30,
            cwd=base_dir or None
        )
        output = ''
        if result.stdout:
            output += result.stdout
        if result.stderr:
            if output:
                output += '\n'
            output += result.stderr
        if not output:
            output = '(exit code %d)' % result.returncode
        return _truncate(output)
    except subprocess.TimeoutExpired:
        return 'Error: execution timed out (30s limit)'
    except Exception as e:
        return "Error executing Python: %s" % e


@_register('web_fetch')
def _execute_web_fetch(arguments, base_dir):
    """获取网页文本内容"""
    url = arguments.get('url', '')
    if not url:
        return "Error: 'url' argument is required"
    # 基本 URL 校验
    if not url.startswith(('http://', 'https://')):
        return "Error: URL must start with http:// or https://"
    try:
        import requests
        resp = requests.get(url, timeout=15, headers={
            'User-Agent': 'llm-engine/1.0'
        })
        resp.raise_for_status()
        text = resp.text
        # 简单去除 HTML 标签
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', '', text)
        # 压缩多余空行
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        return _truncate(text)
    except Exception as e:
        return "Error fetching URL: %s" % e


@_register('view_image')
def _execute_view_image(arguments, base_dir):
    """查看图片文件，返回包含 base64 数据的特殊结果"""
    path = arguments.get('path', '')
    if not path:
        return "Error: 'path' argument is required"
    path = _resolve_path(path, base_dir)

    if not os.path.exists(path):
        return "Error: image file not found: %s" % path

    try:
        with open(path, 'rb') as f:
            image_data = f.read()

        # 检测图片类型
        if image_data[:8] == b'\x89PNG\r\n\x1a\n':
            media_type = 'image/png'
        elif image_data[:3] == b'\xff\xd8\xff':
            media_type = 'image/jpeg'
        elif image_data[:4] == b'GIF8':
            media_type = 'image/gif'
        elif image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
            media_type = 'image/webp'
        else:
            media_type = 'image/png'

        base64_data = base64.b64encode(image_data).decode('utf-8')
        size_kb = len(image_data) / 1024

        # 返回特殊的 dict 结构，engine.py 会识别并注入图片到对话中
        return {
            "_image": True,
            "text": "Image loaded: %s (%s, %.1fKB)" % (path, media_type, size_kb),
            "base64": base64_data,
            "media_type": media_type,
        }
    except Exception as e:
        return "Error reading image: %s" % e
