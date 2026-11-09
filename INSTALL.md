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
4. 安装 micro 插件到 `~/.config/micro/plug/llm_micro`（Windows 为 `%APPDATA%/micro/plug/llm_micro`）

也可以只安装部分组件：
```bash
python install.py --vim      # 仅安装 Vim 插件
python install.py --vscode   # 仅安装 VSCode 扩展
python install.py --micro    # 仅安装 micro 插件
python install.py --pip      # 仅安装 pip 包
```

默认以**符号链接**方式安装（可编辑安装）：仓库内改动即时生效，
`git pull` 即升级，但要求仓库目录保持原位不可删除。
如果希望安装后与仓库解耦（可移动或删除仓库目录），加 `--copy` 以拷贝
方式安装（同时 pip 改为常规安装）：
```bash
python install.py --copy           # 全部组件拷贝安装
python install.py --copy --vim     # 仅 Vim 插件拷贝安装
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
mkdir -p ~/.vim/plugin ~/.vim/ftdetect ~/.vim/doc
cp vim/plugin/llm.vim ~/.vim/plugin/
cp vim/ftdetect/llm.vim ~/.vim/ftdetect/
cp vim/doc/llm.txt ~/.vim/doc/
vim -c 'helptags ~/.vim/doc' -c 'qa!'   # 使 :help llm 生效
```

#### 包管理器安装

##### Vim-Plug
在 `~/.vimrc` 中添加（`rtp` 选项指定插件素材所在的子目录）：
```vim
Plug 'your-username/llm_with_vim', {'rtp': 'vim/'}
```

##### Vundle
Vundle 不支持指定子目录，请改用上面的 Vim-Plug 或 `install.py` 安装。

然后运行 `:PlugInstall`

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

### micro 插件安装

#### 自动安装（推荐）

```bash
python install.py --micro
```

说明：自动安装会把插件目录复制到 micro 插件路径（不是符号链接）。删除项目源码目录后，micro 插件仍可继续使用。

#### 手动安装

```bash
mkdir -p ~/.config/micro/plug
ln -s /path/to/llm_with_vim/micro/llm_micro ~/.config/micro/plug/llm_micro
```

Windows 手动安装目录：`%APPDATA%\\micro\\plug\\llm_micro`

安装后重启 micro，默认快捷键：

- `F1` 提交上下文
- `Shift+K` 中断请求
- `F2` 显示大纲
- `F3` 预览当前行 `$$...$$` 图片
