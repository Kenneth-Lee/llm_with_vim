# -*- coding: utf-8 -*-
"""bash 工具插件：执行 bash 命令。"""
import subprocess

from llm_engine.plugin_loader import CFPlugin, CFP_Tool
from llm_engine.tools import truncate


class BashTool(CFP_Tool):
    name = 'bash'
    func_name = 'bash'
    description = ('Execute a bash command and return stdout and stderr. '
                   'Commands have a 30-second timeout.')
    parameters = {
        'type': 'object',
        'properties': {
            'command': {
                'type': 'string',
                'description': 'The bash command to execute',
            },
        },
        'required': ['command'],
    }

    def execute(self, arguments, context):
        base_dir = context.get('base_dir', '')
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
            return truncate(output)
        except subprocess.TimeoutExpired:
            return 'Error: command timed out (30s limit)'
        except Exception as e:
            return "Error executing command: %s" % e


CFPlugin.register(BashTool)
