# -*- coding: utf-8 -*-
"""list_dir 工具插件：列出目录内容。"""
import os

from llm_engine.plugin_loader import CFPlugin, CFP_Tool
from llm_engine.tools import resolve_path


class ListDirTool(CFP_Tool):
    name = 'list_dir'
    func_name = 'list_dir'
    description = ('List directory contents. Returns file and directory '
                   'names, with \'/\' suffix for directories.')
    parameters = {
        'type': 'object',
        'properties': {
            'path': {
                'type': 'string',
                'description': 'Directory path to list '
                               '(default: working directory)',
            },
        },
        'required': [],
    }

    def execute(self, arguments, context):
        base_dir = context.get('base_dir', '')
        path = arguments.get('path', '') or base_dir or '.'
        path = resolve_path(path, base_dir)
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


CFPlugin.register(ListDirTool)
