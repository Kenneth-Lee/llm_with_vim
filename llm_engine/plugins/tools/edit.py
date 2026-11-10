# -*- coding: utf-8 -*-
"""edit 工具插件：精确字符串替换编辑。"""
from llm_engine.plugin_loader import CFPlugin, CFP_Tool
from llm_engine.tools import resolve_path


class EditTool(CFP_Tool):
    name = 'edit'
    func_name = 'edit_file'
    description = ('Replace an exact string occurrence in a file with new '
                   'content. The old_string must match exactly (including '
                   'whitespace and indentation). Use for precise, surgical '
                   'edits.')
    parameters = {
        'type': 'object',
        'properties': {
            'path': {
                'type': 'string',
                'description': 'File path to edit (absolute or relative '
                               'to working directory)',
            },
            'old_string': {
                'type': 'string',
                'description': 'The exact string to find and replace. Must '
                               'match exactly one location in the file.',
            },
            'new_string': {
                'type': 'string',
                'description': 'The replacement string. Use empty string to '
                               'delete the old_string.',
            },
        },
        'required': ['path', 'old_string', 'new_string'],
    }

    def execute(self, arguments, context):
        base_dir = context.get('base_dir', '')
        path = arguments.get('path', '')
        old_string = arguments.get('old_string', '')
        new_string = arguments.get('new_string', '')
        if not path:
            return "Error: 'path' argument is required"
        if not old_string:
            return "Error: 'old_string' argument is required"
        path = resolve_path(path, base_dir)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            count = content.count(old_string)
            if count == 0:
                return "Error: old_string not found in %s" % path
            if count > 1:
                return ("Error: old_string found %d times in %s "
                        "(must be exactly 1)" % (count, path))
            new_content = content.replace(old_string, new_string, 1)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return "Successfully edited %s" % path
        except Exception as e:
            return "Error editing file: %s" % e


CFPlugin.register(EditTool)
