# -*- coding: utf-8 -*-
"""read 工具插件：读取文件内容。"""
from llm_engine.plugin_loader import CFPlugin, CFP_Tool
from llm_engine.tools import resolve_path, truncate


class ReadTool(CFP_Tool):
    name = 'read'
    func_name = 'read_file'
    description = ('Read the contents of a file at the given path. '
                   'Returns the file content as text.')
    parameters = {
        'type': 'object',
        'properties': {
            'path': {
                'type': 'string',
                'description': 'File path to read (absolute or relative '
                               'to working directory)',
            },
        },
        'required': ['path'],
    }

    def execute(self, arguments, context):
        base_dir = context.get('base_dir', '')
        path = arguments.get('path', '')
        if not path:
            return "Error: 'path' argument is required"
        path = resolve_path(path, base_dir)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            return truncate(content)
        except Exception as e:
            return "Error reading file: %s" % e


CFPlugin.register(ReadTool)
