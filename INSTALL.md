# 安装指南

## 快速安装

如果你已经下载源代码了，而且打算就放在某个目录下用，那么你直接用一键安装脚本就行了：

```bash
python install.py
```

脚本会依次完成：

1. pip 安装 llm\_engine 包（提供 `llm_engine` 命令）
2. 检测 Vim/Neovim/GVim，符号链接插件到 `~/.vim/`（Windows 为 `~/vimfiles/`）
3. 检测 VSCode/VSCode Insiders/VSCodium，符号链接扩展到扩展目录

也可以只安装部分组件：
```bash
python install.py --vim      # 仅安装 Vim 插件
python install.py --vscode   # 仅安装 VSCode 扩展
python install.py --pip      # 仅安装 pip 包
```

支持 Linux、macOS 和 Windows

## 独立安装

如果你需要按标准的方式管理python软件包和vim，vscode的插件，可以参考本小节的方法。

### 安装LLM Engine

通过 pip 安装 LLM 引擎：
```bash
# 从项目目录安装
pip install .

# 或者开发模式安装（方便更新）
pip install -e .
```

安装后会在 PATH 中提供 `llm_engine` 命令。

###  安装VIM插件

#### 手动安装

```bash
mkdir -p ~/.vim/plugin ~/.vim/ftdetect
cp plugin/llm.vim ~/.vim/plugin/
cp ftdetect/llm.vim ~/.vim/ftdetect/
```

#### 包管理器安装

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
