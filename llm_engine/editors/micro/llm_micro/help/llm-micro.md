# LLM Micro Plugin

在 micro 编辑器中使用 `llm_engine` 处理 `.llm` 对话文件。

## 默认快捷键

- `F1`: 提交从文件开头到当前光标行的上下文
- `Ctrl+K` 或 `Alt+K`: 中断正在进行的 LLM 请求
- `F3`: 预览当前行中的 `$$path/to/image$$` 图片

## 命令

- `> llmsubmit`
- `> llmstop`
- `> llmimg`
- `> llmdoctor`

## 说明

- 仅对 `.llm` 文件生效。
- Linux/macOS 下插件会通过 `sh` 查找并运行引擎（`llm_engine`、`llm-engine`、`python3 -m llm_engine`、`python -m llm_engine`）。
- Windows 下插件会通过 `cmd.exe /c` 查找并运行引擎（`llm_engine`、`llm-engine`、`py -3 -m llm_engine`、`python -m llm_engine`）。
- 请求完成后会在结果末尾自动追加 `User: `，方便继续多轮对话。
- 如 micro 环境变量不包含你的 PATH，可显式指定：
	`> set llm_micro.enginecmd '/absolute/path/to/llm_engine'`
	兼容写法：`> set plugin.llm_micro.enginecmd '/absolute/path/to/llm_engine'`

注意：如果你在其他终端里切换了 venv，但 micro 进程本身没有更新环境变量，micro 里不会自动同步那个“外部终端会话状态”；此时建议重启 micro，或使用 `llm_micro.enginecmd` 显式指定。

Windows 建议优先用以下方式显式指定引擎（可避免 PATH 不一致）：
`> set llm_micro.enginecmd 'py -3 -m llm_engine'`

另：`Shift+K` 在终端中通常只会表现为输入大写 `K`，不能稳定作为独立快捷键，因此 micro 版默认不再使用它做中断。

## 生效检查

- `> plugin list` 中应看到 `llm_micro`
- 打开 `.llm` 文件后运行 `> set filetype` 应显示 `llm-chat`
- 运行 `> llmdoctor` 可查看当前 PATH 与引擎探测结果