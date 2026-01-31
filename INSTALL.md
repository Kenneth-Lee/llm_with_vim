# LLM Chat 插件安装指南

## Vim 插件安装

### 方法 1: 手动安装（推荐）

1. **复制插件文件到 Vim 目录**：
   ```bash
   # 创建必要的目录
   mkdir -p ~/.vim/plugin ~/.vim/ftdetect

   # 复制插件文件（llm_engine.py 必须与 llm.vim 在同一目录）
   cp plugin/llm.vim ~/.vim/plugin/
   cp llm_engine.py ~/.vim/plugin/
   cp ftdetect/llm.vim ~/.vim/ftdetect/
   cp config.json ~/.vim/
   ```

2. **安装 Python 依赖**：
   ```bash
   pip install requests
   ```

3. **重启 Vim**，打开任意 `.llm` 文件即可自动启用插件

### 方法 2: 使用包管理器

#### Vim-Plug
在 `~/.vimrc` 中添加：
```vim
Plug 'your-username/llm_with_vim'
```

#### Vundle
```vim
Plugin 'your-username/llm_with_vim'
```

然后运行 `:PlugInstall` 或 `:PluginInstall`

### 目录结构说明

插件安装后的目录结构应该是：
```
~/.vim/
├── plugin/
│   ├── llm.vim          # 主插件文件
│   └── llm_engine.py    # LLM 引擎脚本（必须与 llm.vim 同目录）
├── ftdetect/
│   └── llm.vim          # 文件类型检测
└── config.json          # 配置文件
```

### llm_engine.py 的查找路径

插件会按以下顺序查找 `llm_engine.py`：
1. 插件目录（`~/.vim/plugin/llm_engine.py`）- **推荐**
2. 插件父目录（`~/.vim/llm_engine.py`）
3. PATH 环境变量
4. 当前工作目录

**重要**：`llm_engine.py` 必须与 `llm.vim` 放在同一目录，或者放在上述查找路径中的某个位置。

### 配置 config.json

编辑 `~/.vim/config.json` 设置默认 LLM 引擎：
```json
{
  "config": {
    "engine_type": "ollama",
    "server_addr": "localhost",
    "model": "qwen2.5:0.5b",
    "keep_alive": 3600
  }
}
```

## VSCode 扩展安装

### 方法 1: 开发模式（测试用）

1. 在 VSCode 中打开 `vscode/` 目录
2. 按 `F5` 启动扩展开发主机
3. 在新窗口中打开 `.llm` 文件使用

### 方法 2: 符号链接安装（推荐）

```bash
# 创建符号链接
ln -s /path/to/llm_with_vim/vscode ~/.vscode/extensions/llm-chat-0.1.0

# 将 llm_engine.py 复制到扩展目录
cp llm_engine.py ~/.vscode/extensions/llm-chat-0.1.0/
cp llm_engine.json ~/.vscode/extensions/llm-chat-0.1.0/

# 重启 VSCode
```

### llm_engine.py 的查找路径（VSCode）

VSCode 扩展会按以下顺序查找：
1. 扩展目录（`~/.vscode/extensions/llm-chat-0.1.0/llm_engine.py`）
2. 扩展父目录
3. 工作区根目录

**推荐做法**：将 `llm_engine.py` 和 `llm_engine.json` 放在扩展目录下。

### 方法 3: 打包安装

```bash
# 安装 vsce（需要良好的网络环境）
npm install -g @vscode/vsce

# 打包
cd vscode
vsce package

# 安装
code --install-extension llm-chat-0.1.0.vsix
```

## 使用方法

### Vim

1. 创建 `.llm` 文件：
   ```bash
   vim test.llm
   ```

2. 输入对话内容：
   ```
   Configure: {'engine_type': 'ollama', 'model': 'qwen2.5:0.5b'}
   User: Hello, how are you?
   ```

3. 按 `F1` 或在插入模式输入 `jj` 提交查询
4. 按 `K`（大写）中断生成
5. 按 `F2` 显示对话大纲

### VSCode

1. 打开 `.llm` 文件
2. 按 `F1` 提交查询
3. 按 `Shift+K` 中断生成
4. 按 `F2` 显示对话大纲

## 环境检查

首次打开 `.llm` 文件时，插件会自动检查：
- Python 3 是否安装
- llm_engine.py 是否可找到
- requests 包是否安装

如果检查失败，会显示错误信息。

## 故障排除

### Vim: "llm_engine.py 未找到"

解决方法：
1. 确认 `llm_engine.py` 和 `llm.vim` 在同一目录（如 `~/.vim/plugin/`）
2. 或者将其添加到 PATH 环境变量
3. 或者放在当前工作目录

### "找不到配置文件 config.json"

解决方法：
1. 确认 `config.json` 与 `llm_engine.py` 在同一目录
2. 如果 `llm_engine.py` 在 `~/.vim/plugin/`，那么 `config.json` 也应该在 `~/.vim/plugin/` 或 `~/.vim/`

### "Python环境缺少必需的包"

解决方法：
```bash
pip install requests
```

### VSCode: "llm_engine.py 未找到"

解决方法：
1. 将 `llm_engine.py` 复制到扩展目录
2. 或者放在工作区根目录

## 高级配置

### 自定义 API 密钥

在 `.llm` 文件的 Configure 行中添加：
```
Configure: {'engine_type': 'deepseek', 'auth': 'Bearer sk-xxxxxxxx'}
```

### 多引擎配置

编辑 `config.json` 的 `auth_keys` 部分：
```json
{
  "auth_keys": {
    "deepseek": "Bearer sk-xxxxxxxx",
    "zhipu": "Bearer xxxxxxxx",
    "ali": "Bearer sk-xxxxxxxx"
  }
}
```

**注意**：建议将 API 密钥配置在每个 `.llm` 文件的 Configure 行中，而不是 `config.json`，因为后者可能在更新时被覆盖。
