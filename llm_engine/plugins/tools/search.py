# -*- coding: utf-8 -*-
"""search 工具插件：在文件中搜索文本模式。"""
import subprocess

from llm_engine.plugin_loader import CFPlugin, CFP_Tool
from llm_engine.tools import resolve_path, truncate


class SearchTool(CFP_Tool):
    name = 'search'
    func_name = 'grep_search'
    description = ('Search for a text pattern (regex supported) in files '
                   'under a directory. Returns matching lines with file '
                   'paths and line numbers.')
    parameters = {
        'type': 'object',
        'properties': {
            'pattern': {
                'type': 'string',
                'description': 'The search pattern (grep extended regex)',
            },
            'path': {
                'type': 'string',
                'description': 'Directory or file to search in '
                               '(default: working directory)',
            },
            'include': {
                'type': 'string',
                'description': 'File glob pattern to include, '
                               'e.g. \'*.py\' (optional)',
            },
        },
        'required': ['pattern'],
    }

    def execute(self, arguments, context):
        base_dir = context.get('base_dir', '')
        pattern = arguments.get('pattern', '')
        if not pattern:
            return "Error: 'pattern' argument is required"
        path = arguments.get('path', '') or base_dir or '.'
        path = resolve_path(path, base_dir)
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
            return truncate(output)
        except subprocess.TimeoutExpired:
            return 'Error: search timed out (30s limit)'
        except Exception as e:
            return "Error searching: %s" % e


CFPlugin.register(SearchTool)
