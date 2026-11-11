"""LLM Engine - 处理.llm文件并发送给LLM服务"""

import sys
import os

# 获取文件编码：优先从环境变量获取
_file_encoding = os.environ.get('LLM_FILE_ENCODING', '')
if not _file_encoding:
    _file_encoding = 'utf-8'

# 确保编码是有效的，否则回退到 utf-8
try:
    'test'.encode(_file_encoding)
except LookupError:
    _file_encoding = 'utf-8'

# Windows 下重设置标准流的编码（stdin、stdout、stderr）
if sys.platform == 'win32':
    import io
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding=_file_encoding, errors='replace')
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding=_file_encoding, errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding=_file_encoding, errors='replace')

__version__ = "2.0.20261111"

from llm_engine.engine import answer

def main():
    answer()
