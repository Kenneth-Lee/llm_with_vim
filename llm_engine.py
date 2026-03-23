#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Engine - 处理.llm文件并发送给LLM服务
"""

from __future__ import print_function
import sys
import json
import time
import os
import requests
import signal

# Python 2/3 兼容
if sys.version_info[0] == 2:
    import ConfigParser as configparser
else:
    import configparser

# 全局配置
_config = None
_verbose_mode = False

# Ollama地址别名
_ollama_addr_alias = {
    'default': 'localhost',
    'home': '192.168.31.100',
    'aliyun': '47.98.228.76',
    'txyun': '43.139.74.214',
}

# Ollama模型别名
_ollama_model_alias = {
    'qwen': 'qwen2.5:0.5b',
    'llama': 'llama3.2:1b',
    'deepseek': 'deepseek-r1:1.5b',
}

# 角色前缀定义
_roles = {
    "system":    "System: ",
    "user":      "User: ",
    "assistant": "Assistant: ",
    "config":    "Configure: ",
}

def _load_config():
    """加载配置文件"""
    global _config
    if _config is None:
        config_file = os.path.join(os.path.dirname(__file__), 'llm_engine.json')
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                _config = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            sys.exit(1)
    return _config

def _make_ollama_api(host, api='chat'):
    """构建Ollama API地址"""
    if host.startswith("http"):
        return host + api
    else:
        return 'http://' + host + ':11434/api/' + api

def debug(msg):
    """输出调试信息到stdout（作为注释）"""
    print(f"// {msg}")

def verbose_debug(msg):
    """输出详细调试信息（需要verbose=True才输出）"""
    if _verbose_mode:
        print(f"// {msg}")

def _add_msg(req, role, content):
    """给请求增加某个角色的消息"""
    if content and content.strip():
        req['messages'].append({"role": role, "content": content.strip()})

def _parse_input():
    """
    处理stdin的输入信息。返回history, config。

    核心设计：
    - 所有文件（主文件和头文件）都一行一行顺序处理
    - 维护当前角色状态，延续内容追加到当前角色
    - 遇到@inc时压栈，处理完头文件后弹栈继续，保持角色状态连续
    """
    global _config
    history = _config["request_template"]
    history["messages"] = []
    user_config = None

    # 读取主输入文件
    main_lines = sys.stdin.readlines()

    # 堆栈：每个元素是 (lines, line_idx, base_dir, depth, is_main_file)
    stack = [(main_lines, 0, '', 0, True)]
    MAX_DEPTH = 10

    # 状态机状态
    current_role = 'none'   # 当前角色
    current_content = ''    # 当前角色累积的内容
    role_outputted = False  # 当前角色是否已输出到output_lines

    # 输出收集
    output_lines = []

    # 标记主文件是否输出了Config
    main_file_has_config = False

    def flush_role():
        """提交当前角色的内容"""
        nonlocal user_config, current_role, current_content, role_outputted, main_file_has_config

        if not current_content.strip():
            return

        content = current_content

        if current_role == 'config':
            # Config 更新 user_config（后覆盖前）
            user_config = content.strip()
        elif current_role != 'none':
            # 其他角色添加到 history
            _add_msg(history, current_role, content)

        # 重置当前内容
        current_content = ''
        role_outputted = False

    def output_line(is_main_file, line_to_output):
        """输出一行内容到output_lines（仅主文件）"""
        nonlocal main_file_has_config, current_role, role_outputted

        if not is_main_file:
            return

        if not line_to_output.strip():
            output_lines.append(line_to_output)
            return

        if current_role == 'config':
            if not role_outputted:
                output_lines.append(_roles['config'] + line_to_output.strip() + '\n')
                main_file_has_config = True
                role_outputted = True
            else:
                output_lines.append(line_to_output)
        elif current_role != 'none':
            if not role_outputted:
                # 第一次输出该角色，添加角色前缀
                role_msg = _roles.get(current_role, current_role + ": ")
                output_lines.append(role_msg + line_to_output)
                role_outputted = True
            else:
                # 延续内容，不加前缀
                output_lines.append(line_to_output)

    while stack:
        current_lines, line_idx, base_dir, depth, is_main_file = stack[-1]

        # 检查是否当前文件处理完毕
        if line_idx >= len(current_lines):
            # 弹栈，继续处理上一个文件
            stack.pop()
            if not stack:
                # 所有文件处理完毕
                flush_role()
                break
            continue

        line = current_lines[line_idx]
        stack[-1] = (current_lines, line_idx + 1, base_dir, depth, is_main_file)

        # 处理不同类型的行
        if line.startswith("/"):                # 调试信息，忽略
            continue

        elif line.startswith("#"):              # 注释
            flush_role()
            if is_main_file:
                output_lines.append(line)
            current_role = 'none'

        elif line.startswith("@inc "):           # @inc 原语
            flush_role()
            if is_main_file:
                output_lines.append(line)
            current_role = 'none'

            # 检查深度限制
            if depth >= MAX_DEPTH:
                debug(f"@inc: maximum nesting depth ({MAX_DEPTH}) exceeded")
                continue

            # 解析文件名
            parts = line.strip().split(None, 1)
            if len(parts) < 2:
                debug(f"Invalid @inc directive: {line.strip()}")
                continue

            filename = parts[1].strip()

            # 验证文件名
            if os.path.isabs(filename) or '..' in filename:
                debug(f"@inc: invalid path: {filename}")
                continue

            # 构建完整路径
            file_path = os.path.join(base_dir, filename) if base_dir else filename
            file_path = os.path.normpath(file_path)
            if '..' in file_path:
                debug(f"@inc: path traversal not allowed: {filename}")
                continue

            # 读取被包含的文件
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except (FileNotFoundError, IOError, UnicodeDecodeError) as e:
                debug(f"@inc: error reading {filename}: {e}")
                continue

            # 获取被包含文件的目录
            file_dir = os.path.dirname(filename)
            new_base_dir = file_dir if file_dir else base_dir

            # 压栈处理头文件
            inc_lines = content.splitlines(keepends=True)
            stack.append((inc_lines, 0, new_base_dir, depth + 1, False))

        else:                                   # 普通内容行
            # 检查是否是新角色
            found_role = None
            for role_name, role_prefix in _roles.items():
                if line.startswith(role_prefix):
                    found_role = role_name
                    break

            if found_role:
                # 新角色，提交当前角色内容
                flush_role()
                current_role = found_role
                # 提取内容（去掉角色前缀）
                prefix = _roles[found_role]
                current_content = line[len(prefix):] if line.startswith(prefix) else line
                # 头文件中的新角色定义需要标记已输出（虽然不真实输出到output_lines）
                if not is_main_file:
                    role_outputted = True
                    # 如果头文件中有config角色，也标记主文件已有config
                    if found_role == 'config':
                        main_file_has_config = True
                else:
                    # 主文件的新角色定义直接输出原始行（已包含前缀）
                    output_lines.append(line)
                    role_outputted = True
                    # 如果是config角色，标记主文件已有config
                    if found_role == 'config':
                        main_file_has_config = True
            else:
                # 延续当前角色
                current_content += line
                # 延续行只有主文件输出
                if is_main_file:
                    output_line(is_main_file, line)

    # 所有文件处理完毕，如果主文件没有Config但有user_config，插入到开头
    if not main_file_has_config and user_config:
        output_lines.insert(0, _roles['config'] + user_config + '\n')

    # 输出所有收集的行
    sys.stdout.write(''.join(output_lines))
    sys.stdout.flush()

    if user_config:
        try:
            import ast
            try:
                uc = json.loads(user_config)
            except json.JSONDecodeError:
                uc = ast.literal_eval(user_config)

            if not isinstance(uc, dict):
                raise ValueError("Configuration must be a dictionary/object")
            return history, uc
        except (json.JSONDecodeError, ValueError, SyntaxError):
            debug(f"Invalid user config: {user_config}")
            debug("Configuration must be in JSON format like {\"key\": \"value\"} or Python dict format like {'key': 'value'}")
            return history, None

    return history, None

def _validate_config_value(name, value, expected_type=None):
    """Validate configuration values to prevent malicious inputs"""
    if expected_type and not isinstance(value, expected_type):
        return False

    if isinstance(value, str):
        dangerous_patterns = [';', '|', '&', '`', '$(', '${', '\x00']
        for pattern in dangerous_patterns:
            if pattern in value:
                return False
        if len(value) > 10000:
            return False

    if isinstance(value, (int, float)):
        if name in ['max_tokens', 'temperature', 'keep_alive'] and (value < 0 or value > 100000):
            return False

    return True

def _get_user_config_item(name, default, user_config):
    """获取配置项，优先级：用户配置 > 全局配置 > 默认值"""
    global _config
    config = _config["config"]

    c = config.get(name, default)
    if user_config:
        user_value = user_config.get(name)
        if user_value is not None:
            if _validate_config_value(name, user_value, type(default) if default is not None else None):
                return user_value
            else:
                debug(f"Invalid configuration value for '{name}', using default")
                return c
        return c
    return c

def answer():
    """主函数：处理输入并发送给LLM"""
    global _config, _verbose_mode
    _load_config()

    start_time = time.time()

    # 处理输入
    history, user_config = _parse_input()

    # 获取verbose配置（尽早获取，以便后续调试信息能正确输出）
    _verbose_mode = _get_user_config_item("verbose", False, user_config)

    # API请求头部
    headers = {'Content-Type': 'application/json'}

    # 组合配置
    common_config = _config['default_config']
    engine_type = _get_user_config_item("engine_type", "ollama", user_config)
    server_addr = _get_user_config_item("server_addr", "localhost", user_config)
    for key in common_config.keys():
        common_config[key] = _get_user_config_item(key, common_config[key], user_config)
    if engine_type == "ollama":
        keep_alive = _get_user_config_item("keep_alive", 60, user_config)

    # 获取超时配置
    connect_timeout = common_config.get('connect_timeout', 30)
    read_timeout = common_config.get('read_timeout', 1800)
    timeout = (connect_timeout, read_timeout)

    # 根据引擎类型设置默认参数
    if engine_type == 'haijing':
        if common_config['model'] == '' or common_config['model'] == 'default':
            common_config['model'] = 'DeepSeek-R1'
        api = 'https://api.atalk-ai.com/chat/completions'
    elif engine_type == 'deepseek':
        if common_config['model'] == '' or common_config['model'] == 'default':
            common_config['model'] = 'deepseek-chat'
        api = 'https://api.deepseek.com/chat/completions'
    elif engine_type == 'zhipu':
        if common_config['model'] == '' or common_config['model'] == 'default':
            common_config['model'] = 'glm-4.7'
        api = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
    elif engine_type == 'ali':
        if common_config['model'] == '' or common_config['model'] == 'default':
            common_config['model'] = 'deepseek-r1'
        api = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
    elif engine_type == 'llama':
        api = 'http://' + server_addr + '/v1/chat/completions'
    elif engine_type == 'ollama':
        if common_config['model'] == '' or common_config['model'] == 'default':
            common_config['model'] = 'qwen2.5:0.5b'
        server_addr = _ollama_addr_alias.get(server_addr, server_addr)
        common_config['model'] = _ollama_model_alias.get(
            common_config['model'], common_config['model'])
        api = _make_ollama_api(server_addr)
    else:
        # 未知引擎作为默认的 OpenAI 兼容引擎处理（支持 vLLM 等）
        # server_addr 格式: host:port 或完整 URL
        debug(f"使用 OpenAI 兼容引擎: {engine_type}")
        if server_addr.startswith("http"):
            api = server_addr.rstrip('/') + '/v1/chat/completions'
        else:
            api = 'http://' + server_addr + '/v1/chat/completions'
        debug(f"API地址: {api}")
        engine_type = 'openai_compat'

    # API key处理（提前处理，以便模型查询时使用）
    if engine_type not in ['ollama', 'llama']:
        auth = user_config.get('auth', None) if user_config else None
        if not auth:
            auth_keys = _config.get("auth_keys", {})
            auth = auth_keys.get(engine_type, '')
        if auth:
            headers['Authorization'] = auth

    # 如果 model 为 "request"，查询可用模型列表
    if common_config['model'] == 'TELLME':
        models = []
        try:
            if engine_type == 'ollama':
                # Ollama 使用 /api/tags 查询模型
                tags_api = _make_ollama_api(server_addr, 'tags')
                resp = requests.get(tags_api, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                if 'models' in data:
                    models = [m['name'] for m in data['models']]
            elif engine_type in ['openai_compat', 'llama']:
                # OpenAI 兼容引擎使用 /v1/models 查询模型
                models_api = api.rsplit('/', 2)[0] + '/v1/models'
                req_headers = {}
                if 'Authorization' in headers:
                    req_headers['Authorization'] = headers['Authorization']
                resp = requests.get(models_api, headers=req_headers, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                if 'data' in data:
                    models = [m['id'] for m in data['data']]
        except Exception as e:
            print(f"// 查询模型失败: {e}")
            sys.exit(0)

        if models:
            print(f"// 可用模型列表 (共 {len(models)} 个):")
            for m in models:
                print(f"//   {m}")
            print("// 请将 Configure 中的 model 设置为上述模型之一")
        else:
            print("// 未找到可用模型")
        sys.exit(0)

    # 没有给用户配置的生成一个
    if not user_config:
        user_config = common_config.copy()
        user_config["engine_type"] = engine_type
        user_config["server_addr"] = server_addr
        if engine_type == 'ollama':
            user_config["keep_alive"] = keep_alive
        debug(f"{_roles['config']} {user_config}")

    # 根据配置完善请求记录
    for key in common_config.keys():             # 所有common_config中的配置导入请求中
        history[key] = common_config[key]
    if engine_type == 'ollama':
        history["keep_alive"] = keep_alive
    if engine_type != 'llama':
        history["stream"] = True

    # 详细调试信息（需要verbose=True才输出）
    verbose_debug(f"engine_type={engine_type}")
    verbose_debug(f"api={api}")
    verbose_debug(f"headers={headers}")
    verbose_debug(f"history={history}")
    debug("===========>")

    # 发起请求
    resp = None
    response_completed = False
    try:
        resp = requests.post(api, json=history, headers=headers, stream=True, timeout=timeout)
        resp.raise_for_status()

        print(_roles['assistant'], end='', flush=True)
        if engine_type == 'haijing':
            for i in resp.iter_lines():
                if i:
                    try:
                        decoded_line = i.decode('utf-8')
                        print(decoded_line)
                    except UnicodeDecodeError:
                        continue
        elif engine_type == 'zhipu':
            for i in resp.iter_lines():
                if i:
                    try:
                        decoded_line = i.decode('utf-8')
                        if decoded_line.startswith('data:'):
                            resp_s = decoded_line.split("data:", 1)[-1].strip()
                            if resp_s == '[DONE]':
                                break
                            else:
                                try:
                                    resp_i = json.loads(resp_s)
                                    if 'choices' in resp_i and len(resp_i['choices']) > 0:
                                        delta_content = resp_i['choices'][0].get('delta', {}).get('content', '')
                                        if delta_content:
                                            print(delta_content, end='', flush=True)
                                except json.JSONDecodeError:
                                    pass
                    except UnicodeDecodeError:
                        continue
        elif engine_type == 'ali':
            for i in resp.iter_lines():
                if i:
                    try:
                        decoded_line = i.decode('utf-8')
                        if decoded_line.startswith('data:'):
                            resp_s = decoded_line.split("data:", 1)[-1].strip()
                            if resp_s == '[DONE]':
                                break
                            else:
                                try:
                                    resp_i = json.loads(resp_s)
                                    if 'choices' in resp_i and len(resp_i['choices']) > 0:
                                        delta_content = resp_i['choices'][0].get('delta', {}).get('content', '')
                                        if delta_content:
                                            print(delta_content, end='', flush=True)
                                except json.JSONDecodeError:
                                    pass
                    except UnicodeDecodeError:
                        continue
        elif engine_type == 'ollama':
            for i in resp.iter_lines():
                if i:
                    try:
                        resp_i = json.loads(i.decode('utf-8'))
                        if 'message' in resp_i:
                            content = resp_i['message'].get('content', '')
                            if content:
                                print(content, end='', flush=True)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
        elif engine_type == 'llama':
            for i in resp.iter_lines():
                if i:
                    try:
                        resp_i = json.loads(i.decode('utf-8'))
                        if 'choices' in resp_i and len(resp_i['choices']) > 0:
                            content = resp_i['choices'][0]['message'].get('content', '')
                            if content:
                                print(content, end='', flush=True)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
        else:
            # OpenAI 兼容引擎（vLLM 等）的流式响应处理
            for i in resp.iter_lines():
                if i:
                    try:
                        decoded_line = i.decode('utf-8')
                        if decoded_line.startswith('data:'):
                            resp_s = decoded_line.split("data:", 1)[-1].strip()
                            if resp_s == '[DONE]':
                                break
                            else:
                                try:
                                    resp_i = json.loads(resp_s)
                                    if 'choices' in resp_i and len(resp_i['choices']) > 0:
                                        delta_content = resp_i['choices'][0].get('delta', {}).get('content', '')
                                        if delta_content:
                                            print(delta_content, end='', flush=True)
                                except json.JSONDecodeError:
                                    pass
                    except UnicodeDecodeError:
                        continue
        response_completed = True
        print()
    except requests.exceptions.Timeout:
        print()
        if not response_completed:
            debug("API request timed out.")
    except requests.exceptions.ConnectionError:
        print()
        if not response_completed:
            debug("Connection error occurred.")
    except requests.exceptions.HTTPError as e:
        print()
        debug(f"HTTP error occurred: {e}")
    except Exception as e:
        print()
        debug(f"Unexpected error occurred: {e}")

    print(f"//updated at {time.asctime()} in {(time.time()-start_time):.1f} seconds", end='')

if __name__ == "__main__":
    answer()
