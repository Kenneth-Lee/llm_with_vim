# -*- coding: utf-8 -*-
"""view_image 工具插件：查看图片文件，返回包含 base64 数据的特殊结果。"""
import base64
import os

from llm_engine.plugin_loader import CFPlugin, CFP_Tool
from llm_engine.tools import resolve_path


class ViewImageTool(CFP_Tool):
    name = 'view_image'
    func_name = 'view_image'
    description = ('View an image file and return its visual content. '
                   'Supports PNG, JPEG, GIF, WebP formats. The image will '
                   'be sent to the vision model for analysis.')
    parameters = {
        'type': 'object',
        'properties': {
            'path': {
                'type': 'string',
                'description': 'Image file path (absolute or relative '
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

        if not os.path.exists(path):
            return "Error: image file not found: %s" % path

        try:
            with open(path, 'rb') as f:
                image_data = f.read()

            # 检测图片类型
            if image_data[:8] == b'\x89PNG\r\n\x1a\n':
                media_type = 'image/png'
            elif image_data[:3] == b'\xff\xd8\xff':
                media_type = 'image/jpeg'
            elif image_data[:4] == b'GIF8':
                media_type = 'image/gif'
            elif image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
                media_type = 'image/webp'
            else:
                media_type = 'image/png'

            base64_data = base64.b64encode(image_data).decode('utf-8')
            size_kb = len(image_data) / 1024

            # 返回特殊的 dict 结构，engine.py 会识别并注入图片到对话中
            return {
                "_image": True,
                "text": "Image loaded: %s (%s, %.1fKB)" % (
                    path, media_type, size_kb),
                "base64": base64_data,
                "media_type": media_type,
            }
        except Exception as e:
            return "Error reading image: %s" % e


CFPlugin.register(ViewImageTool)
