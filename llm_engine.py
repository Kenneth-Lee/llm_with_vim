#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Engine - 向后兼容的入口脚本。
推荐安装方式: pip install llm-engine
"""

import os
import sys

# 将项目根目录加入搜索路径，使 llm_engine 包可被导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm_engine import main

if __name__ == "__main__":
    main()

