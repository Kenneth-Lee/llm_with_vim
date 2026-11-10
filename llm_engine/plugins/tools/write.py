# -*- coding: utf-8 -*-
"""write 工具插件：写入文件内容。"""
import os

from llm_engine.plugin_loader import CFPlugin, CFP_Tool
from llm_engine.tools import resolve_path


class WriteTool(CFP_Tool):
    name = 'write'
    func_name = 'write_file'
    description = ('Write content to a file, creating it if it doesn\'t exist '
                   'or overwriting if it does. Parent directories are created '
                   'automatically.')
    parameters = {
        'type': 'object',
        'properties': {
            'path': {
                'type': 'string',
                'description': 'File path to write (absolute or relative '
                               'to working directory)',
            },
            'content': {
                'type': 'string',
                'description': 'The content to write to the file',
            },
        },
        'required': ['path', 'content'],
    }

    def execute(self, arguments, context):
        base_dir = context.get('base_dir', '')
        path = arguments.get('path', '')
        content = arguments.get('content', '')
        if not path:
            return "Error: 'path' argument is required"
        path = resolve_path(path, base_dir)
        try:
            parent = os.path.dirname(path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return "Successfully wrote %d chars to %s" % (len(content), path)
        except Exception as e:
            return "Error writing file: %s" % e


CFPlugin.register(WriteTool)
