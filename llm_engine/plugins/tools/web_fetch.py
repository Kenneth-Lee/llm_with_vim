# -*- coding: utf-8 -*-
"""web_fetch 工具插件：获取网页文本内容。"""
import re

from llm_engine.plugin_loader import CFPlugin, CFP_Tool
from llm_engine.tools import truncate


class WebFetchTool(CFP_Tool):
    name = 'web_fetch'
    func_name = 'web_fetch'
    description = ('Fetch the text content of a web URL. Returns the page '
                   'body as plain text (HTML tags stripped). Has a '
                   '15-second timeout.')
    parameters = {
        'type': 'object',
        'properties': {
            'url': {
                'type': 'string',
                'description': 'The URL to fetch',
            },
        },
        'required': ['url'],
    }

    def execute(self, arguments, context):
        url = arguments.get('url', '')
        if not url:
            return "Error: 'url' argument is required"
        # 基本 URL 校验
        if not url.startswith(('http://', 'https://')):
            return "Error: URL must start with http:// or https://"
        try:
            import requests
            resp = requests.get(url, timeout=15, headers={
                'User-Agent': 'llm-engine/1.0'
            })
            resp.raise_for_status()
            text = resp.text
            # 简单去除 HTML 标签
            text = re.sub(r'<script[^>]*>.*?</script>', '', text,
                          flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text,
                          flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', '', text)
            # 压缩多余空行
            text = re.sub(r'\n{3,}', '\n\n', text).strip()
            return truncate(text)
        except Exception as e:
            return "Error fetching URL: %s" % e


CFPlugin.register(WebFetchTool)
