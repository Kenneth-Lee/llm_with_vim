# -*- coding: utf-8 -*-
"""
LLM Engine Tools - 工具定义与执行
"""

import os
import json
import subprocess


# 可用工具定义（OpenAI function calling 格式）
TOOL_REGISTRY = {
    'read': {
        'type': 'function',
        'function': {
            'name': 'read_file',
            'description': 'Read the contents of a file at the given path',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': 'File path to read (absolute or relative to working directory)'
                    }
                },
                'required': ['path']
            }
        }
    },
    'bash': {
        'type': 'function',
        'function': {
            'name': 'bash',
            'description': 'Execute a bash command and return stdout and stderr',
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {
                        'type': 'string',
                        'description': 'The bash command to execute'
                    }
                },
                'required': ['command']
            }
        }
    },
}

# 工具名到函数名的映射（一个工具组可包含多个 function）
_TOOL_FUNCTIONS = {
    'read_file': 'read',
    'bash': 'bash',
}

MAX_OUTPUT_SIZE = 100000


def get_tool_definitions(tool_names):
    """根据工具名列表返回 OpenAI 格式的工具定义"""
    tools = []
    for name in tool_names:
        if name in TOOL_REGISTRY:
            tools.append(TOOL_REGISTRY[name])
    return tools


def execute_tool(func_name, arguments, base_dir=''):
    """执行工具并返回结果字符串"""
    if func_name == 'read_file':
        return _execute_read(arguments, base_dir)
    elif func_name == 'bash':
        return _execute_bash(arguments, base_dir)
    return f"Error: unknown tool function '{func_name}'"


def _execute_read(arguments, base_dir):
    """读取文件内容"""
    path = arguments.get('path', '')
    if not path:
        return "Error: 'path' argument is required"

    if not os.path.isabs(path) and base_dir:
        path = os.path.join(base_dir, path)
    path = os.path.normpath(path)

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        if len(content) > MAX_OUTPUT_SIZE:
            content = content[:MAX_OUTPUT_SIZE] + f'\n... (truncated, total {len(content)} chars)'
        return content
    except Exception as e:
        return f"Error reading file: {e}"


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
            output = f'(exit code {result.returncode})'
        if len(output) > MAX_OUTPUT_SIZE:
            output = output[:MAX_OUTPUT_SIZE] + f'\n... (truncated)'
        return output
    except subprocess.TimeoutExpired:
        return 'Error: command timed out (30s limit)'
    except Exception as e:
        return f"Error executing command: {e}"
