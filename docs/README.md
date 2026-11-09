# 文档目录说明

本项目有两个文档目录，注意区分：

| 目录 | 用途 |
|------|------|
| `docs/` | 项目开发/设计文档（本目录），主要为引导 AI 协作的设计文档 |
| `vim/doc/` | **Vim 插件帮助文档**（如 `vim/doc/llm.txt`），与 `vim/plugin/`、`vim/ftdetect/` 同属 Vim 插件素材，供 `:help llm` 使用 |

Vim 插件的全部素材（`plugin/`、`ftdetect/`、`doc/`）集中在 `vim/` 子目录下，
与 `vscode/`、`micro/` 目录对称；`install.py` 从该目录安装到 `~/.vim/` 并生成 helptags。
