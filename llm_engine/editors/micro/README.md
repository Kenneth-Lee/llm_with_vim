# LLM Chat Assistant for Micro

这是一个 Micro 插件，将 llm_with_vim 项目的核心交互能力移植到 Micro 中，让你可以在 `.llm` 文件里进行可编辑的 LLM 对话。

## 功能特性

- **交互式对话编辑**: 在 `.llm` 文件中直接编辑上下文，随时重提问、改历史
- **多引擎支持**: 复用 `llm_engine`，支持 Ollama / DeepSeek / 智谱 / 阿里等
- **语法高亮**: 自动识别 `User`、`Assistant`、`System`、`Configure` 角色
- **快速导航**: `F2` 生成 `User/Configure` 大纲，配合 `llmjump` 快速跳转
- **便捷操作**:
  - `F1`: 提交从文件开头到光标行的上下文
  - `Ctrl+K` 或 `Alt+K`: 中断正在进行的请求
  - `F2`: 显示大纲
  - `F3`: 预览当前行 `$$...$$` 图片引用

## 安装方法

### 方法 1: 安装命令（推荐）

```bash
pip install llm-with-vim
llm-with-vim-setup --micro
```

或从源码仓库：

```bash
python install.py --micro
```

安装后插件目录为：

- Linux/macOS: `~/.config/micro/plug/llm_micro`
- Windows: `%APPDATA%\\micro\\plug\\llm_micro`

### 方法 2: 手动安装

```bash
mkdir -p ~/.config/micro/plug
cp -r /path/to/llm_with_vim/micro/llm_micro ~/.config/micro/plug/llm_micro
```

安装后重启 Micro。

## 使用方法

### 快速开始示例

1. 创建并打开测试文件：

```bash
cat > ~/tmp/test-micro.llm <<'EOF'
Configure: {'engine_type': 'ollama', 'server_addr': 'localhost', 'model': 'qwen2.5:0.5b'}
User: 你好，请介绍一下你自己
EOF
micro ~/tmp/test-micro.llm
```

2. 将光标放在最后一个 `User:` 段落
3. 按 `F1` 提交
4. 等待响应，输出会自动追加在文件中

### 常用命令

- `> llmsubmit`: 提交请求
- `> llmstop`: 中断请求
- `> llmoutline`: 显示大纲
- `> llmjump <编号>`: 跳转到大纲项
- `> llmimg`: 预览当前行图片
- `> llmdoctor`: 诊断引擎与环境

## 环境与排障

### 1. 插件是否生效

- `> plugin list` 中应看到 `llm_micro`
- 打开 `.llm` 后执行 `> set filetype` 应显示 `llm-chat`
- 运行 `> llmoutline` 应看到索引输出

### 2. 找不到 `llm_engine`

先执行：

- `> llmdoctor`

如果仍找不到，可显式指定：

```text
> set llm_micro.enginecmd '/absolute/path/to/llm_engine'
```

Windows 推荐值（避免 PATH 差异）：

```text
> set llm_micro.enginecmd 'py -3 -m llm_engine'
```

### 3. 中断快捷键说明

Micro 终端环境下 `Shift+K` 通常只是输入大写 `K`，不能稳定作为独立快捷键。Micro 插件默认使用：

- `Ctrl+K`
- `Alt+K`

## 与 Vim 版本的区别

- 快捷键不同：
  - Vim 的 `jj` / `<F1>` -> Micro 的 `F1`
  - Vim 的 `K` -> Micro 的 `Ctrl+K` / `Alt+K`
  - Vim 的 `<F2>` -> Micro 的 `F2`
- 大纲交互为命令式导航（`llmoutline` + `llmjump`）
- 不包含 Vim 的 abbreviations 功能
- 执行时通过 `$SHELL -lc` 解析引擎命令，更贴近 shell 环境
