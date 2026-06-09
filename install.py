#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM with Vim/VSCode/Micro - 插件安装脚本

自动检测本地 Vim、VSCode 和 micro 安装，将插件安装到对应目录。
支持 Linux、macOS 和 Windows。

用法:
    python install.py           # 安装 pip 包 + 检测并安装编辑器插件
    python install.py --vim     # 仅安装 Vim 插件
    python install.py --vscode  # 仅安装 VSCode 插件
    python install.py --pip     # 仅安装 pip 包
    python install.py --micro   # 仅安装 micro 插件
"""

import os
import sys
import shutil
import platform
import argparse
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def info(msg):
    print('  \033[32m✓\033[0m ' + msg)


def warn(msg):
    print('  \033[33m⚠\033[0m ' + msg)


def error(msg):
    print('  \033[31m✗\033[0m ' + msg)


def header(msg):
    print('\n\033[1m' + msg + '\033[0m')


# ==================== pip 安装 ====================

def install_pip():
    header('安装 LLM Engine (pip)')
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', '-e', SCRIPT_DIR],
            stdout=subprocess.DEVNULL if not VERBOSE else None
        )
        info('pip install -e . 完成')
        return True
    except subprocess.CalledProcessError:
        error('pip install 失败，请手动运行: pip install -e ' + SCRIPT_DIR)
        return False
    except FileNotFoundError:
        error('找不到 pip，请先安装 pip')
        return False


# ==================== 配置文件 ====================

def install_config():
    """安装用户配置文件到 ~/.config/llm_engine/"""
    system = platform.system()
    if system == 'Windows':
        config_dir = os.path.join(os.environ.get('APPDATA', ''), 'llm_engine')
    else:
        config_dir = os.path.expanduser('~/.config/llm_engine')

    config_file = os.path.join(config_dir, 'llm_engine.json')
    src = os.path.join(SCRIPT_DIR, 'llm_engine', 'default_config.json')

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


def _get_vim_dirs():
    """获取 Vim 插件目录列表（按优先级）"""
    system = platform.system()
    home = os.path.expanduser('~')
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
    installed = False

    for vim_dir in vim_dirs:
        plugin_dir = os.path.join(vim_dir, 'plugin')
        ftdetect_dir = os.path.join(vim_dir, 'ftdetect')
        doc_dir = os.path.join(vim_dir, 'doc')

        os.makedirs(plugin_dir, exist_ok=True)
        os.makedirs(ftdetect_dir, exist_ok=True)
        os.makedirs(doc_dir, exist_ok=True)

        src_plugin = os.path.join(SCRIPT_DIR, 'plugin', 'llm.vim')
        src_ftdetect = os.path.join(SCRIPT_DIR, 'ftdetect', 'llm.vim')
        src_doc = os.path.join(SCRIPT_DIR, 'doc', 'llm.txt')

        if not os.path.exists(src_plugin):
            error('源文件不存在: ' + src_plugin)
            continue

        dst_plugin = os.path.join(plugin_dir, 'llm.vim')
        dst_ftdetect = os.path.join(ftdetect_dir, 'llm.vim')
        dst_doc = os.path.join(doc_dir, 'llm.txt')

        # 使用符号链接（Windows 可能降级为复制）
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

    return installed


# ==================== VSCode 扩展安装 ====================

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

    src_dir = os.path.join(SCRIPT_DIR, 'vscode')
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

        # 使用符号链接
        _link_or_copy_dir(src_dir, target_dir)

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

    src_dir = os.path.join(SCRIPT_DIR, 'micro', 'llm_micro')
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
    """创建符号链接，Windows 下降级为复制"""
    src = os.path.abspath(src)
    if os.path.islink(dst):
        os.remove(dst)
    elif os.path.exists(dst):
        os.remove(dst)

    if platform.system() == 'Windows':
        shutil.copy2(src, dst)
    else:
        os.symlink(src, dst)


def _link_or_copy_dir(src, dst):
    """创建目录符号链接，Windows 下降级为复制目录"""
    src = os.path.abspath(src)
    if platform.system() == 'Windows':
        # Windows 上复制目录内容
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        os.symlink(src, dst)


# ==================== 主函数 ====================

def main():
    global VERBOSE
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
    parser.add_argument('--no-pip', action='store_true',
                        help='跳过 pip 安装')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='显示详细输出')
    args = parser.parse_args()

    VERBOSE = args.verbose
    specific = args.vim or args.vscode or args.pip or args.micro

    print('LLM with Vim/VSCode/Micro 安装脚本')
    print('系统: %s (%s)' % (platform.system(), platform.machine()))

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

if __name__ == '__main__':
    main()
