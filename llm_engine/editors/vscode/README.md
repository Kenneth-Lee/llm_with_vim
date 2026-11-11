# LLM Chat Assistant for VSCode

这是一个VSCode插件，将llm_with_vim项目的功能移植到VSCode中，让你能在VSCode中进行可编辑的LLM对话。

## 功能特性

- **交互式对话编辑**: 在.llm文件中编辑LLM对话，可随时修改问题和答案
- **多引擎支持**: 支持Ollama、DeepSeek、智谱AI、阿里云、Haijing、Llama等多个LLM引擎
- **语法高亮**: 自动识别User、Assistant、System、Configure等角色标识
- **快速导航**: 通过F2键显示所有User查询的大纲，快速跳转
- **便捷操作**:
  - Ctrl+Enter: 提交当前位置之前的对话给LLM
  - F4: 打开插件快速帮助（可直接执行提交/替换/中断/大纲）
  - Shift+K: 中止正在进行的LLM生成
  - F2: 显示对话大纲

## 安装方法

### 生成并安装.vsix文件

```bash
# 进入vscode目录
cd /home/kenny/work/llm_with_vim/vscode

# 安装vsce工具(如未安装)
npm install -g @vscode/vsce

# 打包生成.vsix文件
vsce package

# 安装生成的.vsix文件
code --install-extension llm-with-vscode-1.0.20260129.vsix
```

安装完成后重启VSCode即可使用。

## 使用方法

### 快速开始示例

1. 创建一个测试文件：
   ```bash
   cd /home/kenny/work/llm_with_vim
   code test-vscode.llm
   ```

2. 在文件中输入：
   ```
   Configure: {'engine_type': 'ollama', 'model': 'qwen2.5:0.5b'}
   User: 你好，请介绍一下你自己
   ```

3. 将光标放在 `User:` 那行
4. 按 `Ctrl+Enter` 键提交查询
5. 等待LLM响应，内容会自动显示在 `Assistant:` 行后

## 与Vim版本的区别

- 快捷键略有不同：
  - Vim的`jj`/`<F1>` → VSCode的`Ctrl+Enter`
  - Vim的`<F4>`/`:LLMHelp` → VSCode的`F4` 或命令面板 `LLM: Show Help`
  - Vim的`K` → VSCode的`Shift+K`
  - Vim的`<F2>` → VSCode的`F2`
- 使用VSCode的QuickPick显示大纲，而非独立窗口
- 使用VSCode的进度通知显示生成状态
- 不支持Vim版本的所有语法功能（如abbreviations）
