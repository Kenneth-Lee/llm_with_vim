# LLM Chat Assistant for VSCode

这是一个VSCode插件，将llm_with_vim项目的功能移植到VSCode中，让你能在VSCode中进行可编辑的LLM对话。

## 功能特性

- **交互式对话编辑**: 在.txt文件中编辑LLM对话，可随时修改问题和答案
- **多引擎支持**: 支持Ollama、DeepSeek、智谱AI、阿里云、Haijing、Llama等多个LLM引擎
- **语法高亮**: 自动识别User、Assistant、System、Configure等角色标识
- **快速导航**: 通过F2键显示所有User查询的大纲，快速跳转
- **便捷操作**: 
  - F1: 提交当前位置之前的对话给LLM
  - Shift+K: 中止正在进行的LLM生成
  - F2: 显示对话大纲

## 安装方法

### 方式1: 开发模式（推荐）

这是最简单和推荐的方式：

1. 确保已安装Node.js和VSCode

2. 用VSCode打开vscode目录：
   ```bash
   code /home/kenny/work/llm_with_vim/vscode
   ```

3. 在VSCode中按 `F5` 键（或点击左侧调试图标，然后点击"Run Extension"）

4. 会弹出一个新的VSCode窗口，标题显示"[Extension Development Host]"

5. 在新窗口中打开或创建.txt文件即可使用

> **说明**: 项目中已包含 `.vscode/launch.json` 配置文件，VSCode会自动识别这是一个扩展项目。开发模式下每次修改代码后可以直接重新加载（Ctrl+R），非常方便。

### 方式2: 符号链接安装（用于日常使用）

如果想在所有VSCode窗口中使用该插件，可以创建符号链接：

```bash
# 创建符号链接到VSCode的扩展目录
ln -s /home/kenny/work/llm_with_vim/vscode ~/.vscode/extensions/llm-with-vscode-0.1.0

# 重启VSCode
```

安装后可以通过扩展面板查看已安装的扩展。

### 方式3: 打包安装（需要vsce工具）

如果网络允许安装vsce工具，可以使用标准打包方式：

```bash
# 安装vsce（需要良好的网络环境）
npm install -g @vscode/vsce

# 打包
cd /home/kenny/work/llm_with_vim/vscode
vsce package

# 安装
code --install-extension llm-with-vscode-0.1.0.vsix
```

> **注意**: 由于国内网络原因，安装vsce可能会超时。推荐使用方式1（开发模式）或方式2（符号链接）。

## 使用方法

### 快速开始示例

1. 创建一个测试文件：
   ```bash
   cd /home/kenny/work/llm_with_vim
   code test-vscode.txt
   ```

2. 在文件中输入：
   ```
   Configure: {'engine_type': 'ollama', 'model': 'qwen2.5:0.5b'}
   User: 你好，请介绍一下你自己
   ```

3. 将光标放在 `User:` 那行
4. 按 `F1` 键提交查询
5. 等待LLM响应，内容会自动显示在 `Assistant:` 行后

### 对话格式

按照以下格式编写对话：

```
Configure:  {'engine_type': 'ollama', 'model': 'qwen2.5:0.5b', 'temperature': 1}
System: 你是一个AI助手
// 这是注释
User: 你的问题
Assistant: LLM的回答会自动生成在这里
User: 继续提问
```

### 常用操作

- **提交查询**: 将光标移动到某个User行，按 `F1` 提交从文档开头到当前位置的对话
- **中止生成**: 按 `Shift+K` 可以随时中止正在进行的LLM生成
- **快速导航**: 按 `F2` 显示所有User查询的大纲，选择后跳转到对应位置
- **编辑历史**: 可以随时修改之前的User问题或Assistant回答，重新提交会基于修改后的内容生成新回答

## 配置说明

插件会使用父目录的`config.json`和`llama.py`脚本。确保：
- Python 3.6+已安装
- 父目录的config.json配置正确
- llama.py可执行

## 与Vim版本的区别

- 快捷键略有不同：
  - Vim的`jj`/`<F1>` → VSCode的`F1`
  - Vim的`K` → VSCode的`Shift+K`
  - Vim的`<F2>` → VSCode的`F2`
- 使用VSCode的QuickPick显示大纲，而非独立窗口
- 使用VSCode的进度通知显示生成状态

## 已知限制

- 目前仅支持.txt文件
- 需要Python和llama.py脚本支持
- 不支持Vim版本的所有语法功能（如abbreviations）

## 开发

如需修改插件：
1. 编辑`extension.js`修改核心逻辑
2. 编辑`syntaxes/llm-chat.tmLanguage.json`修改语法高亮
3. 编辑`package.json`修改命令和快捷键

## 许可证

遵循主项目的LICENSE
