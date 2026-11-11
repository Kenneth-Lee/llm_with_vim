#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM with Vim/VSCode/Micro - 编辑器插件安装

自动检测本地 Vim、VSCode 和 micro 安装，将插件安装到对应目录。
支持 Linux、macOS 和 Windows。

两种使用方式：
  1. git clone 用户：仓库根目录 install.py 薄壳调用本模块
  2. pip/uv 安装用户：llm-with-vim-setup 命令（本模块 main 入口）

用法:
    python install.py           # 安装 pip 包 + 检测并安装编辑器插件
    python install.py --vim     # 仅安装 Vim 插件
    python install.py --vscode  # 仅安装 VSCode 插件
    python install.py --pip     # 仅安装 pip 包
    python install.py --micro   # 仅安装 micro 插件
    python install.py --copy    # 拷贝方式安装（默认符号链接；拷贝后与仓库解耦）

uv 用户：
    - 推荐独立工具方式（命令进 ~/.local/bin，不依赖虚拟环境激活）:
        uv tool install --editable <仓库路径>
        python install.py --no-pip
    - 在 uv 管理的虚拟环境中运行本脚本时，若环境无 pip 模块
      （uv venv 默认不装），会自动改用 uv pip 安装。

默认符号链接（可编辑安装）：仓库内改动即时生效，git pull 即升级，
但要求仓库目录保持原位不可删除。加 --copy 则全部改为拷贝（含 pip
常规安装），安装后可移动/删除仓库，代价是仓库更新后需重新运行安装。
"""

import os
import sys
import shutil
import platform
import argparse
import subprocess

# 包内路径（编辑器插件随包分发在 llm_engine/editors/ 下）
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
EDITORS_ROOT = os.path.join(PACKAGE_DIR, 'editors')
# 仓库根目录（仅 git clone 场景存在，供 pip 可编辑安装用）
REPO_ROOT = os.path.dirname(PACKAGE_DIR)

try:
    from llm_engine.provider_spec import get_config_root
except ImportError:  # 直接以脚本方式运行本文件时（非常规用法）
    sys.path.insert(0, REPO_ROOT)
    from llm_engine.provider_spec import get_config_root


def info(msg):
    print('  \033[32m✓\033[0m ' + msg)


def warn(msg):
    print('  \033[33m⚠\033[0m ' + msg)


def error(msg):
    print('  \033[31m✗\033[0m ' + msg)


def header(msg):
    print('\n\033[1m' + msg + '\033[0m')


# ==================== pip 安装 ====================

def _pip_available():
    """当前解释器是否有可用的 pip 模块（uv venv 默认不附带 pip）"""
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', '--version'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def install_pip():
    header('安装 LLM Engine')
    if not os.path.isfile(os.path.join(REPO_ROOT, 'pyproject.toml')):
        # 已通过 pip/uv 安装了本包（非 git clone 场景），引擎已就绪
        info('引擎已随 pip 包安装，跳过')
        return None

    # --copy 时常规安装（不依赖本仓库）；默认 -e 可编辑安装（仓库内改代码即生效）
    editable = not COPY_MODE
    uv_bin = shutil.which('uv')

    use_uv = False
    if not _pip_available():
        if uv_bin:
            use_uv = True
            warn('当前环境没有 pip 模块，改用 uv pip 安装')
        else:
            error('当前 Python 环境没有 pip，也未找到 uv，请手动安装（二选一）:')
            error('  pip install -e ' + REPO_ROOT)
            error('  uv tool install --editable ' + REPO_ROOT)
            return False

    if use_uv:
        cmd = [uv_bin, 'pip', 'install', '--python', sys.executable]
        manual = '%s pip install --python %s' % (uv_bin, sys.executable)
    else:
        cmd = [sys.executable, '-m', 'pip', 'install']
        manual = 'pip install'
    if editable:
        cmd.append('-e')
        manual += ' -e'
    cmd.append(REPO_ROOT)
    manual += ' ' + REPO_ROOT

    try:
        subprocess.check_call(
            cmd,
            stdout=subprocess.DEVNULL if not VERBOSE else None
        )
        info('安装完成: ' + manual)
        return True
    except subprocess.CalledProcessError:
        error('安装失败，请手动运行: ' + manual)
        error('uv 用户也可以: uv tool install --editable ' + REPO_ROOT)
        return False
    except FileNotFoundError:
        error('找不到安装工具，请先安装 pip 或 uv')
        return False


# ==================== 配置文件 ====================

def install_config():
    """安装用户配置文件到 ~/.config/llm-with-vim/"""
    config_dir = get_config_root()
    config_file = os.path.join(config_dir, 'config.json')
    src = os.path.join(PACKAGE_DIR, 'default_config.json')

    if os.path.exists(config_file):
        info('配置文件已存在: ' + config_file)
        return

    if not os.path.exists(src):
        return

    os.makedirs(config_dir, exist_ok=True)
    shutil.copy2(src, config_file)
    info('配置文件已安装到: ' + config_file)


# ==================== Vim 插件安装 ====================

def _find_vim():
    """查找 vim 可执行文件"""
    for cmd in ('vim', 'nvim', 'gvim'):
        if shutil.which(cmd):
            return cmd
    return None


def _vim_home():
    """与 Vim 的家目录解析规则保持一致（:help $HOME-windows）

    Vim 顺序: $HOME > $HOMEDRIVE$HOMEPATH > $USERPROFILE；
    而 Python expanduser 优先 USERPROFILE。公司环境（HOME 被设置、
    漫游配置文件重定向）下两者会指向不同目录，导致插件装到
    vim 根本不读的位置。
    """
    if platform.system() == 'Windows':
        home = os.environ.get('HOME')
        if home:
            return os.path.normpath(home)
        drive = os.environ.get('HOMEDRIVE')
        path = os.environ.get('HOMEPATH')
        if drive and path:
            return os.path.normpath(os.path.join(drive, path))
    return os.path.expanduser('~')


def _query_vim_home(vim_cmd):
    """问 vim 自己家目录在哪（最权威，避免任何环境变量解析差异）"""
    if vim_cmd not in ('vim', 'gvim'):
        return None
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix='cf_vimhome_', suffix='.txt')
    os.close(fd)
    vim_path = tmp.replace('\\', '/')
    try:
        subprocess.check_call(
            [vim_cmd, '--not-a-term', '-u', 'NONE', '-n',
             '-c', "call writefile([expand('~')], '%s')" % vim_path,
             '-c', 'qa!'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15)
        with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
            home = f.read().strip()
        return home or None
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _get_vim_dirs(vim_home=None):
    """获取 Vim 插件目录列表（按优先级）"""
    system = platform.system()
    home = vim_home or _vim_home()
    dirs = []

    if system == 'Windows':
        # Windows: ~/vimfiles
        dirs.append(os.path.join(home, 'vimfiles'))
    else:
        # Linux/macOS: ~/.vim
        dirs.append(os.path.join(home, '.vim'))

    # Neovim 路径
    if system == 'Windows':
        nvim_dir = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'nvim')
    elif system == 'Darwin':
        nvim_dir = os.path.join(home, '.config', 'nvim')
    else:
        nvim_dir = os.path.join(home, '.config', 'nvim')

    if os.path.isdir(nvim_dir):
        dirs.append(nvim_dir)

    return dirs


def install_vim():
    header('安装 Vim 插件')

    vim_cmd = _find_vim()
    if not vim_cmd:
        warn('未检测到 Vim/Neovim/GVim，跳过 Vim 插件安装')
        return False

    info('检测到: ' + vim_cmd)

    vim_dirs = _get_vim_dirs()

    # 问 vim 自己家目录在哪；与推测不一致时补装一份并提示
    # （Windows 上 HOME/HOMEDRIVE 与 USERPROFILE 不一致时会出现这种情况）
    vim_reported = _query_vim_home(vim_cmd)
    if vim_reported:
        guessed = _vim_home()
        if os.path.normpath(vim_reported) != os.path.normpath(guessed):
            extra = os.path.join(vim_reported, 'vimfiles')
            if extra not in vim_dirs:
                warn('vim 报告的家目录(%s)与默认推测(%s)不一致，两处都会安装'
                     % (vim_reported, guessed))
                vim_dirs.append(extra)

    installed = False

    for vim_dir in vim_dirs:
        plugin_dir = os.path.join(vim_dir, 'plugin')
        ftdetect_dir = os.path.join(vim_dir, 'ftdetect')
        doc_dir = os.path.join(vim_dir, 'doc')

        os.makedirs(plugin_dir, exist_ok=True)
        os.makedirs(ftdetect_dir, exist_ok=True)
        os.makedirs(doc_dir, exist_ok=True)

        src_plugin = os.path.join(EDITORS_ROOT, 'vim', 'plugin', 'llm.vim')
        src_ftdetect = os.path.join(EDITORS_ROOT, 'vim', 'ftdetect', 'llm.vim')
        src_doc = os.path.join(EDITORS_ROOT, 'vim', 'doc', 'llm.txt')

        if not os.path.exists(src_plugin):
            error('源文件不存在: ' + src_plugin)
            continue

        dst_plugin = os.path.join(plugin_dir, 'llm.vim')
        dst_ftdetect = os.path.join(ftdetect_dir, 'llm.vim')
        dst_doc = os.path.join(doc_dir, 'llm.txt')

        # 默认符号链接（--copy 或 Windows 时为拷贝）
        _link_or_copy(src_plugin, dst_plugin)
        if os.path.exists(src_ftdetect):
            _link_or_copy(src_ftdetect, dst_ftdetect)
        if os.path.exists(src_doc):
            _link_or_copy(src_doc, dst_doc)
            # 生成 helptags，使 :help llm 生效
            # 优先用当前 vim_cmd，降级到 'vim'，再降级到 'nvim'
            for cmd in (vim_cmd, 'vim', 'nvim'):
                if cmd:
                    try:
                        subprocess.check_call(
                            [cmd, '--not-a-term', '-c',
                             'helptags ' + doc_dir, '-c', 'qa!'],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
                        break
                    except Exception:
                        pass

        info('Vim 插件已安装到: ' + vim_dir)
        installed = True

    if installed:
        info('验证: 用 vim 打开 .llm 文件后执行 :LLMHelp 应弹出帮助；'
             '未激活时按 README.md "安装后 vim 插件未激活的排查"一节检查')

    return installed


# ==================== VSCode 扩展安装 ====================

# 拷贝安装时排除的开发期文件（符号链接不占额外空间，无需排除）
_VSCODE_DEV_JUNK = shutil.ignore_patterns(
    'node_modules', '.vscode', 'package-lock.json', '.npmrc',
    '.gitignore', '*.vsix')

def _find_vscode():
    """查找 VSCode 可执行文件，返回 (命令名, 扩展目录)"""
    system = platform.system()
    home = os.path.expanduser('~')
    results = []

    # 可能的 code 命令
    code_cmds = ['code', 'code-insiders', 'codium']

    # 扩展目录映射
    if system == 'Windows':
        ext_dirs = {
            'code': os.path.join(os.environ.get('USERPROFILE', home),
                                 '.vscode', 'extensions'),
            'code-insiders': os.path.join(os.environ.get('USERPROFILE', home),
                                          '.vscode-insiders', 'extensions'),
            'codium': os.path.join(os.environ.get('USERPROFILE', home),
                                   '.vscode-oss', 'extensions'),
        }
    elif system == 'Darwin':
        ext_dirs = {
            'code': os.path.join(home, '.vscode', 'extensions'),
            'code-insiders': os.path.join(home,
                                          '.vscode-insiders', 'extensions'),
            'codium': os.path.join(home, '.vscode-oss', 'extensions'),
        }
    else:
        ext_dirs = {
            'code': os.path.join(home, '.vscode', 'extensions'),
            'code-insiders': os.path.join(home,
                                          '.vscode-insiders', 'extensions'),
            'codium': os.path.join(home, '.vscode-oss', 'extensions'),
        }

    for cmd in code_cmds:
        if shutil.which(cmd):
            ext_dir = ext_dirs.get(cmd, '')
            results.append((cmd, ext_dir))

    return results


def install_vscode():
    header('安装 VSCode 扩展')

    vscode_list = _find_vscode()
    if not vscode_list:
        # 没找到命令，但扩展目录可能存在
        home = os.path.expanduser('~')
        for d in ['.vscode', '.vscode-insiders', '.vscode-oss']:
            ext_dir = os.path.join(home, d, 'extensions')
            if os.path.isdir(ext_dir):
                vscode_list.append(('(目录存在)', ext_dir))

    if not vscode_list:
        warn('未检测到 VSCode/VSCodium，跳过 VSCode 扩展安装')
        return False

    src_dir = os.path.join(EDITORS_ROOT, 'vscode')
    if not os.path.isdir(src_dir):
        error('源目录不存在: ' + src_dir)
        return False

    installed = False
    for code_cmd, ext_dir in vscode_list:
        info('检测到: ' + code_cmd)

        if not ext_dir:
            warn('无法确定扩展目录，跳过')
            continue

        # 使用 publisher.name 格式作为扩展目录名
        ext_name = 'llm-with-vim.llm-with-vscode'
        target_dir = os.path.join(ext_dir, ext_name)

        # 如果目标已存在且是符号链接，先删除
        if os.path.islink(target_dir):
            os.remove(target_dir)
        elif os.path.isdir(target_dir):
            shutil.rmtree(target_dir)

        os.makedirs(ext_dir, exist_ok=True)

        # 默认符号链接（--copy 或 Windows 时为拷贝）；拷贝时排除开发期文件
        _link_or_copy_dir(src_dir, target_dir, ignore=_VSCODE_DEV_JUNK)

        info('VSCode 扩展已安装到: ' + target_dir)
        installed = True

    return installed


# ==================== micro 插件安装 ====================

def _micro_config_dir():
    """与 micro 的 internal/config.InitConfigDir 一致（不含 -config-dir）。"""
    micro_home = (os.environ.get('MICRO_CONFIG_HOME') or '').strip()
    if micro_home:
        return os.path.abspath(os.path.expanduser(micro_home))
    xdg_home = (os.environ.get('XDG_CONFIG_HOME') or '').strip()
    if not xdg_home:
        xdg_home = os.path.join(os.path.expanduser('~'), '.config')
    else:
        xdg_home = os.path.abspath(os.path.expanduser(xdg_home))
    return os.path.join(xdg_home, 'micro')


def _find_micro_dirs():
    """返回 micro 插件目录候选列表（与 micro 实际配置目录对齐，并保留常见兼容路径）"""
    system = platform.system()
    home = os.path.expanduser('~')

    if system == 'Windows':
        candidates = []

        # micro 默认与 Linux 相同：MICRO_CONFIG_HOME / XDG_CONFIG_HOME/micro / ~/.config/micro
        candidates.append(os.path.join(_micro_config_dir(), 'plug'))

        appdata = os.environ.get('APPDATA', '')
        if appdata:
            candidates.append(os.path.join(appdata, 'micro', 'plug'))

        candidates.append(os.path.join(home, '.config', 'micro', 'plug'))
        candidates.append(os.path.join(home, 'micro', 'plug'))

        seen = set()
        result = []
        for p in candidates:
            if p and p not in seen:
                seen.add(p)
                result.append(p)
        return result

    return [os.path.join(_micro_config_dir(), 'plug')]


def install_micro():
    header('安装 micro 插件')

    src_dir = os.path.join(EDITORS_ROOT, 'micro', 'llm_micro')
    if not os.path.isdir(src_dir):
        warn('未找到 micro 插件目录，跳过')
        return False

    installed = False
    for plug_dir in _find_micro_dirs():
        os.makedirs(plug_dir, exist_ok=True)
        target_dir = os.path.join(plug_dir, 'llm_micro')

        if os.path.islink(target_dir):
            os.remove(target_dir)
        elif os.path.isdir(target_dir):
            shutil.rmtree(target_dir)

        shutil.copytree(src_dir, target_dir)
        info('micro 插件已安装到: ' + target_dir)
        installed = True

    return installed


# ==================== 工具函数 ====================

def _link_or_copy(src, dst):
    """安装单文件：默认符号链接；--copy 或 Windows 下降级为拷贝"""
    src = os.path.abspath(src)
    if os.path.islink(dst):
        os.remove(dst)
    elif os.path.exists(dst):
        os.remove(dst)

    if COPY_MODE or platform.system() == 'Windows':
        shutil.copy2(src, dst)
    else:
        os.symlink(src, dst)


def _link_or_copy_dir(src, dst, ignore=None):
    """安装目录：默认目录符号链接；--copy 或 Windows 下降级为拷贝目录

    ignore: 拷贝时需要排除的模式（如 node_modules），仅拷贝模式生效
    """
    src = os.path.abspath(src)
    if COPY_MODE or platform.system() == 'Windows':
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=ignore)
    else:
        os.symlink(src, dst)


# ==================== 主函数 ====================

def main():
    global VERBOSE, COPY_MODE
    parser = argparse.ArgumentParser(
        description='LLM with Vim/VSCode 插件安装脚本')
    parser.add_argument('--vim', action='store_true',
                        help='仅安装 Vim 插件')
    parser.add_argument('--vscode', action='store_true',
                        help='仅安装 VSCode 扩展')
    parser.add_argument('--pip', action='store_true',
                        help='仅安装 pip 包')
    parser.add_argument('--micro', action='store_true',
                        help='仅安装 micro 插件')
    parser.add_argument('--copy', action='store_true',
                        help='以拷贝方式安装（默认符号链接；拷贝后与仓库解耦，'
                             '仓库更新后需重新运行安装）')
    parser.add_argument('--no-pip', action='store_true',
                        help='跳过 pip 安装')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='显示详细输出')
    args = parser.parse_args()

    VERBOSE = args.verbose
    COPY_MODE = args.copy
    specific = args.vim or args.vscode or args.pip or args.micro

    print('LLM with Vim/VSCode/Micro 安装脚本')
    print('系统: %s (%s)' % (platform.system(), platform.machine()))
    print('安装方式: %s' % ('拷贝（--copy）' if args.copy else '符号链接（可编辑）'))

    results = []

    # pip 安装
    if args.pip or (not specific and not args.no_pip):
        results.append(('pip', install_pip()))
        install_config()

    # Vim 插件
    if args.vim or not specific:
        results.append(('Vim', install_vim()))

    # VSCode 扩展
    if args.vscode or not specific:
        results.append(('VSCode', install_vscode()))

    # micro 插件
    if args.micro or not specific:
        results.append(('micro', install_micro()))

    # 总结
    header('安装总结')
    for name, ok in results:
        if ok:
            info(name + ': 已安装')
        elif ok is False:
            warn(name + ': 跳过')

    print()


VERBOSE = False
COPY_MODE = False

if __name__ == '__main__':
    main()
