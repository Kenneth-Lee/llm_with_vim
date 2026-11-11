#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM with Vim/VSCode/Micro - 仓库安装入口（薄壳）

实际安装逻辑在 llm_engine/install_editors.py，与 pip 安装后的
llm-with-vim-setup 命令共用同一份代码。

用法:
    python install.py           # 安装 pip 包 + 检测并安装编辑器插件
    python install.py --vim     # 仅安装 Vim 插件
    python install.py --vscode  # 仅安装 VSCode 插件
    python install.py --pip     # 仅安装 pip 包
    python install.py --micro   # 仅安装 micro 插件
    python install.py --copy    # 拷贝方式安装（默认符号链接；拷贝后与仓库解耦）

详细说明（uv 用法、可编辑安装等）见 llm_engine/install_editors.py 模块
文档字符串和 INSTALL.md。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm_engine.install_editors import main

if __name__ == '__main__':
    main()
