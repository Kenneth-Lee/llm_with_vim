# -*- coding: utf-8 -*-
"""ContextForge 插件加载器。

插件机制的设计见 docs/plugin_architecture_design.md。要点：

* 插件是一个 py 文件，文件内定义接口类子类并在模块级调用 CFPlugin.register()
  完成自注册（导入即初始化，无 setup/teardown）。
* 哪些插件文件参与运行由插件选择清单 plugins.json 决定：包内清单列出内置
  插件（只读），用户清单（~/.config/contextforge/plugins.json）列出用户插件，
  并可用 disable 字段排除内置插件。
* 主程序通过 CFPlugin.lookup 使用插件：按服务取列表（多选），或按服务加
  名字取单个（单选/分发）。
"""

import importlib.util
import json
import os
import re
import sys


class PluginError(Exception):
    """插件执行失败。消息会作为工具结果返回给 LLM。"""


class CFP_Base(object):
    """插件接口基类：service 必须由子类声明。"""
    service = None


class CFP_Tool(CFP_Base):
    """工具插件接口。

    name      服务内唯一名，即 Configure 行 tools 列表中使用的名字。
    func_name LLM 看到的函数名（OpenAI 定义的 function.name），缺省与
              name 相同。保留两级命名是为了兼容既有会话记录中的工具名。
    """
    service = 'tool'
    name = None
    func_name = None
    description = ''
    parameters = {'type': 'object', 'properties': {}}

    def execute(self, arguments, context):
        """执行工具动作，返回结果字符串；特殊工具（如 view_image）
        可返回带标记的 dict，由调用方识别。context 提供运行环境
        （base_dir 等朴素数据）。"""
        raise NotImplementedError


class CFPlugin(object):
    """插件注册表：{服务名: {插件名: 实例}}。"""

    _registry = {}

    @classmethod
    def register(cls, plugin_cls):
        """插件文件模块级调用：实例化 plugin_cls 并按其 service/name 登记。
        同一服务下同名插件后注册者覆盖先注册者。"""
        service = getattr(plugin_cls, 'service', None)
        name = getattr(plugin_cls, 'name', None)
        if not service or not name:
            raise PluginError(
                'plugin class %s must define service and name' % plugin_cls)
        cls._registry.setdefault(service, {})[name] = plugin_cls()

    @classmethod
    def lookup(cls, service, name=None):
        """按服务取全部插件（多选）；给 name 时取单个插件实例（单选）。"""
        plugins = cls._registry.get(service, {})
        if name is None:
            return list(plugins.values())
        return plugins.get(name)

    @classmethod
    def unregister(cls, service, name):
        """按名字移除插件（用户清单的 disable 字段使用）。"""
        cls._registry.get(service, {}).pop(name, None)

    @classmethod
    def reset(cls):
        """清空注册表（测试用）。"""
        cls._registry = {}


def _warn(msg):
    """插件加载问题输出到 stderr，不混入引擎的 stdout 上下文。"""
    sys.stderr.write('[plugin] %s\n' % msg)


_loaded = False


def get_builtin_plugins_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'plugins')


def get_user_plugins_dir():
    from llm_engine.provider_spec import get_config_root
    return os.path.join(get_config_root(), 'plugins')


def get_user_manifest_path():
    from llm_engine.provider_spec import get_config_root
    return os.path.join(get_config_root(), 'plugins.json')


def _load_manifest(path):
    """读取清单文件，返回 {'load': [...], 'disable': [...]}，不存在则空。"""
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (IOError, OSError, json.JSONDecodeError) as e:
        _warn('manifest %s ignored: %s' % (path, e))
        return {}
    if not isinstance(data, dict):
        _warn('manifest %s ignored: not a json object' % path)
        return {}
    return data


def _import_plugin_file(path):
    """导入一个插件文件；模块级代码执行时自注册。"""
    stem = os.path.splitext(os.path.basename(path))[0]
    module_name = 'cf_plugin_' + re.sub(r'[^0-9A-Za-z_]', '_', stem)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        _warn('cannot load plugin file: %s' % path)
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        sys.modules.pop(module_name, None)
        _warn('plugin %s failed to load: %s' % (path, e))


def _manifest_entries(data, key, base_dir):
    """取清单中的文件条目：相对路径基于 base_dir 解析，绝对路径原样使用。"""
    entries = data.get(key, [])
    if not isinstance(entries, list):
        return []
    paths = []
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            continue
        entry = entry.strip()
        if not os.path.isabs(entry):
            entry = os.path.join(base_dir, entry)
        paths.append(entry)
    return paths


def load_plugins():
    """按选择清单加载全部插件（幂等，重复调用不重新加载；测试时可先
    CFPlugin.reset() 并将 plugin_loader._loaded 置回 False）。

    顺序：先导入包内清单（llm_engine/plugins/plugins.json）中的内置插件，
    然后按用户清单的 disable 字段移除被排除的内置插件（按插件名匹配），
    最后导入用户清单（<config_root>/plugins.json）中的用户插件——同服务
    同名时用户插件覆盖内置插件。
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    builtin_dir = get_builtin_plugins_dir()
    for path in _manifest_entries(
            _load_manifest(os.path.join(builtin_dir, 'plugins.json')),
            'load', builtin_dir):
        _import_plugin_file(path)

    user_data = _load_manifest(get_user_manifest_path())
    for name in user_data.get('disable', []) or []:
        if isinstance(name, str):
            # disable 条目可能给出插件名或清单文件名，都尝试移除
            CFPlugin.unregister('tool', name)
            CFPlugin.unregister('tool', os.path.splitext(name)[0])

    for path in _manifest_entries(user_data, 'load', get_user_plugins_dir()):
        _import_plugin_file(path)
