# LLM Chat 插件安装指南

## 第一步：安装 LLM Engine（必须）

通过 pip 安装 LLM 引擎：
```bash
# 从项目目录安装
pip install .

# 或者开发模式安装（方便更新）
pip install -e .
```

安装后会在 PATH 中提供 `llm_engine` 命令。

### 配置文件

安装后，引擎会按以下顺序查找 `llm_engine.json` 配置文件：
1. `LLM_ENGINE_CONFIG` 环境变量指定的路径
2. `.llm` 文件所在目录
3. 当前工作目录
4. `~/.config/llm_engine/llm_engine.json`（用户配置目录）
5. 包内置默认配置

推荐将自定义配置放在 `~/.config/llm_engine/llm_engine.json`：
```bash
mkdir -p ~/.config/llm_engine
cp llm_engine.json ~/.config/llm_engine/
```

然后编辑该文件设置默认 LLM 引擎：
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

## 第二步：安装编辑器插件

### Vim 插件安装

#### 手动安装

```bash
mkdir -p ~/.vim/plugin ~/.vim/ftdetect
cp plugin/llm.vim ~/.vim/plugin/
cp ftdetect/llm.vim ~/.vim/ftdetect/
```

#### 使用包管理器

##### Vim-Plug
在 `~/.vimrc` 中添加：
```vim
Plug 'your-username/llm_with_vim'
```

##### Vundle
```vim
Plugin 'your-username/llm_with_vim'
```

然后运行 `:PlugInstall` 或 `:PluginInstall`

#### 目录结构说明

插件安装后的目录结构：
```
~/.vim/
├── plugin/
│   └── llm.vim          # 主插件文件
└── ftdetect/
    └── llm.vim          # 文件类型检测
```

插件会按以下顺序查找引擎命令：
1. `llm_engine` 或 `llm-engine` 命令（pip 安装）- **推荐**
2. 插件目录中的 `llm_engine.py`（向后兼容）
3. PATH 中的 `llm_engine.py`

### VSCode 扩展安装

#### 方法 1: 符号链接安装（推荐）

```bash
ln -s /path/to/llm_with_vim/vscode ~/.vscode/extensions/llm-chat-0.1.0
```

重启 VSCode 即可。

VSCode 扩展会按以下顺序查找引擎：
1. `llm_engine` 或 `llm-engine` 命令（pip 安装）- **推荐**
2. 扩展目录中的 `llm_engine.py`（向后兼容）
3. 工作区根目录

#### 方法 2: 打包安装

```bash
npm install -g @vscode/vsce
cd vscode
vsce package
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
