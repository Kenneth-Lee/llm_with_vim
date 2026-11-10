# -*- coding: utf-8 -*-
"""LLM Engine Tools - 工具子系统的门面。

工具本体已插件化：每个工具是 llm_engine/plugins/tools/ 下的一个插件
文件，由 plugin_loader 按选择清单（plugins.json）加载并自注册。
本模块只保留三件事：

* 对 engine.py 的稳定接口（get_tool_definitions / execute_tool 等，
  签名与语义不变）；
* 插件共用的辅助函数（resolve_path / truncate）；
* Configure 行 tools 列表中的名字（如 read）与 LLM 调用名（如
  read_file，即 OpenAI 定义的 function.name）之间的映射，两级命名
  与既有会话记录兼容。
"""

import os

from llm_engine.plugin_loader import CFPlugin, PluginError, load_plugins

MAX_OUTPUT_SIZE = 100000

_loaded = False


def _ensure_loaded():
    global _loaded
    if not _loaded:
        load_plugins()
        _loaded = True


def resolve_path(path, base_dir):
    """解析路径：展开 ~ ，相对路径基于 base_dir"""
    if not path:
        return ''
    path = os.path.expanduser(path)
    if not os.path.isabs(path) and base_dir:
        path = os.path.join(base_dir, path)
    return os.path.normpath(path)


def truncate(text, limit=MAX_OUTPUT_SIZE):
    if len(text) > limit:
        return text[:limit] + '\n... (truncated, total %d chars)' % len(text)
    return text


# 旧私有名兼容别名
_resolve_path = resolve_path
_truncate = truncate


def get_tool_definitions(tool_names):
    """根据工具名列表返回 OpenAI 格式的工具定义"""
    _ensure_loaded()
    tools = []
    for name in tool_names:
        plugin = CFPlugin.lookup('tool', name)
        if plugin is None:
            continue
        tools.append({
            'type': 'function',
            'function': {
                'name': plugin.func_name or plugin.name,
                'description': plugin.description,
                'parameters': plugin.parameters,
            },
        })
    return tools


def get_valid_tool_names(tool_names):
    """返回存在于注册表中的工具名列表。"""
    _ensure_loaded()
    return [name for name in tool_names
            if CFPlugin.lookup('tool', name) is not None]


def get_unknown_tool_names(tool_names):
    """返回未注册的工具名列表。"""
    _ensure_loaded()
    return [name for name in tool_names
            if CFPlugin.lookup('tool', name) is None]


def list_registered_tool_names():
    """返回所有已注册工具名。"""
    _ensure_loaded()
    return sorted(p.name for p in CFPlugin.lookup('tool'))


def _find_tool_by_call_name(func_name):
    """按 LLM 调用名（function.name）找插件，回退到 Configure 工具名。"""
    for plugin in CFPlugin.lookup('tool'):
        if func_name in (plugin.func_name, plugin.name):
            return plugin
    return None


def execute_tool(func_name, arguments, base_dir=''):
    """执行工具并返回结果字符串。

    func_name 接受 LLM 调用名（如 read_file）或 Configure 工具名
    （如 read）。插件返回字符串作为结果；也可返回带标记的 dict
    （view_image 的图片结果），原样返回；抛出的异常转为错误串。"""
    _ensure_loaded()
    plugin = _find_tool_by_call_name(func_name)
    if plugin is None:
        return "Error: unknown tool function '%s'" % func_name
    try:
        return plugin.execute(arguments, {'base_dir': base_dir})
    except PluginError as e:
        return str(e)
    except Exception as e:
        return "Error executing tool: %s" % e
