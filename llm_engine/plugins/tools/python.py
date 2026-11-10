# -*- coding: utf-8 -*-
"""python 工具插件：执行 Python 代码。"""
import subprocess
import sys

from llm_engine.plugin_loader import CFPlugin, CFP_Tool
from llm_engine.tools import truncate


class PythonTool(CFP_Tool):
    name = 'python'
    func_name = 'python'
    description = ('Execute a Python code snippet and return stdout and '
                   'stderr. Code runs with the same Python interpreter as '
                   'llm_engine. Has a 30-second timeout.')
    parameters = {
        'type': 'object',
        'properties': {
            'code': {
                'type': 'string',
                'description': 'Python code to execute',
            },
        },
        'required': ['code'],
    }

    def execute(self, arguments, context):
        base_dir = context.get('base_dir', '')
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
            return truncate(output)
        except subprocess.TimeoutExpired:
            return 'Error: execution timed out (30s limit)'
        except Exception as e:
            return "Error executing Python: %s" % e


CFPlugin.register(PythonTool)
