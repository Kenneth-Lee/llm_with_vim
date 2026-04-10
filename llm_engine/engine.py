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
import re
import base64

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
    """加载配置文件

    配置优先级（从高到低）：
      1. 每个 .llm 文件中的 Configure: 行（运行时覆盖）
      2. 用户配置 ~/.config/llm_engine/llm_engine.json
      3. 包内置默认配置 default_config.json

    用户配置文件只需包含需要修改的部分（如 auth_keys），会与默认配置深度合并。
    也可通过 LLM_ENGINE_CONFIG 环境变量指定用户配置文件路径。
    """
    global _config
    if _config is None:
        # 先加载内置默认配置作为基础
        default_path = os.path.join(
            os.path.dirname(__file__), 'default_config.json')
        try:
            with open(default_path, 'r', encoding='utf-8') as f:
                _config = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print("Error loading default config: %s" % e, file=sys.stderr)
            sys.exit(1)

        # 查找用户配置文件
        user_config_path = os.environ.get('LLM_ENGINE_CONFIG') or \
            os.path.join(os.path.expanduser('~'),
                         '.config', 'llm_engine', 'llm_engine.json')

        if os.path.isfile(user_config_path):
            try:
                with open(user_config_path, 'r', encoding='utf-8') as f:
                    user_cfg = json.load(f)
                _deep_merge(_config, user_cfg)
            except (IOError, json.JSONDecodeError):
                pass

    return _config


def _deep_merge(base, override):
    """深度合并 override 到 base，仅覆盖非注释字段"""
    for key, value in override.items():
        if key.endswith('-comment') or key == 'config-comment':
            continue
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value

def _make_ollama_api(host, api='chat'):
    """构建Ollama API地址"""
    if host.startswith("http"):
        return host + api
    else:
        return 'http://' + host + ':11434/api/' + api

def debug(msg):
    """输出调试信息到stdout（作为注释）"""
    print(f"// {msg}", flush=True)

def verbose_debug(msg):
    """输出详细调试信息（需要verbose=True才输出）"""
    if _verbose_mode:
        print(f"// {msg}", flush=True)

def _encode_image(image_path, base_dir=''):
    """读取图片并转为 base64"""
    # 处理路径
    if os.path.isabs(image_path):
        full_path = image_path
    else:
        full_path = os.path.join(base_dir, image_path) if base_dir else image_path
        full_path = os.path.normpath(full_path)

    try:
        with open(full_path, 'rb') as f:
            image_data = f.read()
        # 检测图片类型
        if image_data[:8] == b'\x89PNG\r\n\x1a\n':
            media_type = 'image/png'
        elif image_data[:3] == b'\xff\xd8\xff':
            media_type = 'image/jpeg'
        elif image_data[:4] == b'GIF8':
            media_type = 'image/gif'
        elif image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
            media_type = 'image/webp'
        else:
            media_type = 'image/png'  # 默认

        base64_data = base64.b64encode(image_data).decode('utf-8')
        return base64_data, media_type, full_path
    except Exception as e:
        debug(f"Error reading image {image_path}: {e}")
        return None, None, full_path

def _extract_images(content, base_dir=''):
    """从内容中提取 $$图片路径$$ 并替换为占位符，返回处理后的内容和图片列表"""
    # 匹配 $$...$$ 格式
    pattern = r'\$\$(.*?)\$\$'
    images = []

    def replace_image(match):
        image_path = match.group(1).strip()
        base64_data, media_type, full_path = _encode_image(image_path, base_dir)
        if base64_data:
            images.append({
                'path': image_path,
                'full_path': full_path,
                'base64': base64_data,
                'media_type': media_type
            })
            return f'[IMAGE:{image_path}]'  # 占位符
        else:
            return f'[IMAGE_NOT_FOUND:{image_path}]'

    processed_content = re.sub(pattern, replace_image, content)
    return processed_content, images

def _add_msg(req, role, content, images=None):
    """给请求增加某个角色的消息，支持多模态"""
    if not content and not images:
        return

    msg = {"role": role}

    if images:
        # 多模态消息格式（Ollama 风格）
        msg["content"] = content.strip() if content else ""
        msg["images"] = [img['base64'] for img in images]
    else:
        msg["content"] = content.strip()

    req['messages'].append(msg)


def _parse_input():
    """
    处理stdin的输入信息。返回history, config。

    核心设计：
    - 所有文件（主文件和头文件）都一行一行顺序处理
    - 维护当前角色状态，延续内容追加到当前角色
    - 遇到@inc时压栈，处理完头文件后弹栈继续，保持角色状态连续
    - 支持 $$图片路径$$ 语法嵌入多模态内容
    """
    global _config
    history = _config["request_template"]
    history["messages"] = []
    user_config = None

    # 存储当前角色的图片
    current_images = []

    # 读取主输入文件
    main_lines = sys.stdin.readlines()

    # 获取基础目录：环境变量优先，默认为当前工作目录
    file_dir = os.environ.get('LLM_FILE_DIR', os.getcwd())

    # 堆栈：每个元素是 (lines, line_idx, base_dir, depth, is_main_file)
    stack = [(main_lines, 0, file_dir, 0, True)]
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
        nonlocal user_config, current_role, current_content, role_outputted, main_file_has_config, current_images

        if not current_content.strip() and not current_images:
            return

        content = current_content

        if current_role == 'config':
            # Config 更新 user_config（后覆盖前）
            user_config = content.strip()
        elif current_role != 'none':
            # 其他角色添加到 history，支持多模态
            _add_msg(history, current_role, content, current_images)

        # 重置当前内容和图片
        current_content = ''
        current_images = []
        role_outputted = False

    def output_line(is_main_file, line_to_output, images=None):
        """输出一行内容到output_lines（仅主文件），支持图片信息"""
        nonlocal main_file_has_config, current_role, role_outputted

        if not is_main_file:
            return

        if not line_to_output.strip() and not images:
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

            # 如果有图片，添加图片引用注释
            if images:
                for img in images:
                    output_lines.append(f"// Image: {img['full_path']}\n")

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
                content_line = line[len(prefix):] if line.startswith(prefix) else line

                # 提取图片（仅在 User 角色中处理）
                if found_role == 'user':
                    processed_content, extracted_images = _extract_images(content_line, base_dir)
                    current_content = processed_content
                    current_images = extracted_images
                else:
                    current_content = content_line
                    current_images = []

                # 头文件中的新角色定义需要标记已输出（虽然不真实输出到output_lines）
                if not is_main_file:
                    role_outputted = True
                    # 如果头文件中有config角色，也标记主文件已有config
                    if found_role == 'config':
                        main_file_has_config = True
                else:
                    # 主文件的新角色定义直接输出原始行（已包含前缀），但图片要特殊处理
                    if found_role == 'user' and current_images:
                        # 输出原始行和图片注释
                        output_lines.append(line)
                        for img in current_images:
                            output_lines.append(f"// Image: {img['full_path']}\n")
                        role_outputted = True
                    else:
                        output_lines.append(line)
                        role_outputted = True
                    # 如果是config角色，标记主文件已有config
                    if found_role == 'config':
                        main_file_has_config = True
            else:
                # 延续当前角色
                if current_role == 'user':
                    # 在 User 角色中继续提取图片
                    processed_line, extracted_images = _extract_images(line, base_dir)
                    current_content += processed_line
                    current_images.extend(extracted_images)
                    # 延续行只有主文件输出
                    if is_main_file:
                        output_line(is_main_file, line, extracted_images)
                else:
                    current_content += line
                    # 延续行只有主文件输出
                    if is_main_file:
                        output_line(is_main_file, line)

    # 所有文件处理完毕，如果主文件没有Config但有user_config，插入到开头
    if not main_file_has_config and user_config:
        output_lines.insert(0, _roles['config'] + user_config + '\n')

    # 输出所有收集的行（保留原始输入，但在图片后添加注释）
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

def _stream_response(resp, engine_type):
    """
    流式解析响应，实时输出文本内容，同时收集工具调用信息。
    返回 (content_text, tool_calls_list)。
    tool_calls 格式: [{'id': str, 'type': 'function',
                       'function': {'name': str, 'arguments': str}}]
    """
    content_parts = []
    # 累积工具调用: index -> {'id', 'type', 'function': {'name', 'arguments'}}
    tool_calls_acc = {}

    if engine_type == 'ollama':
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line.decode('utf-8'))
                message = data.get('message', {})
                c = message.get('content', '')
                if c:
                    print(c, end='', flush=True)
                    content_parts.append(c)
                # Ollama 的 tool_calls 出现在最终消息中
                for i, tc in enumerate(message.get('tool_calls', [])):
                    args = tc.get('function', {}).get('arguments', {})
                    if isinstance(args, dict):
                        args = json.dumps(args, ensure_ascii=False)
                    tool_calls_acc[i] = {
                        'id': tc.get('id', f'call_{i}'),
                        'type': 'function',
                        'function': {
                            'name': tc['function']['name'],
                            'arguments': args
                        }
                    }
            except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
                continue

    elif engine_type == 'haijing':
        for line in resp.iter_lines():
            if line:
                try:
                    decoded = line.decode('utf-8')
                    print(decoded)
                    content_parts.append(decoded + '\n')
                except UnicodeDecodeError:
                    continue

    elif engine_type == 'llama':
        for line in resp.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    if 'choices' in data and data['choices']:
                        c = data['choices'][0].get('message', {}).get('content', '')
                        if c:
                            print(c, end='', flush=True)
                            content_parts.append(c)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

    else:
        # OpenAI 兼容 SSE 格式 (deepseek, zhipu, ali, openai_compat)
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                decoded = line.decode('utf-8')
                if not decoded.startswith('data:'):
                    continue
                payload = decoded.split("data:", 1)[-1].strip()
                if payload == '[DONE]':
                    break

                data = json.loads(payload)
                if 'choices' not in data or not data['choices']:
                    continue

                delta = data['choices'][0].get('delta', {})

                # 文本内容
                c = delta.get('content', '')
                if c:
                    print(c, end='', flush=True)
                    content_parts.append(c)

                # 工具调用（流式累积：name 和 arguments 分多个 chunk 到达）
                for tc_delta in delta.get('tool_calls', []):
                    idx = tc_delta.get('index', 0)
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            'id': '',
                            'type': 'function',
                            'function': {'name': '', 'arguments': ''}
                        }
                    if tc_delta.get('id'):
                        tool_calls_acc[idx]['id'] = tc_delta['id']
                    func_delta = tc_delta.get('function', {})
                    if func_delta.get('name'):
                        tool_calls_acc[idx]['function']['name'] += func_delta['name']
                    if 'arguments' in func_delta:
                        tool_calls_acc[idx]['function']['arguments'] += func_delta['arguments']

            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

    full_content = ''.join(content_parts)
    tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc.keys())]
    return full_content, tool_calls


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

    # 根据配置完善请求记录（只导入 API 认可的请求参数）
    _internal_keys = {'connect_timeout', 'read_timeout', 'verbose',
                       'tools', 'max_tool_rounds'}
    for key in common_config.keys():
        if key not in _internal_keys:
            history[key] = common_config[key]
    if engine_type == 'ollama':
        history["keep_alive"] = keep_alive
    if engine_type != 'llama':
        history["stream"] = True

    # 处理多模态消息格式转换
    def convert_multimodal_messages(messages, engine_type):
        """根据引擎类型转换消息格式"""
        converted = []
        for msg in messages:
            if msg.get('role') == 'user' and 'images' in msg and msg['images']:
                # 有图片的消息
                if engine_type == 'ollama':
                    # Ollama 格式: content + images 数组
                    converted.append({
                        'role': msg['role'],
                        'content': msg.get('content', ''),
                        'images': msg['images']
                    })
                elif engine_type == 'llama':
                    # llama.cpp 格式: 使用 content 数组
                    content_array = []
                    if msg.get('content', '').strip():
                        content_array.append({
                            'type': 'text',
                            'text': msg['content']
                        })
                    for img_base64 in msg['images']:
                        content_array.append({
                            'type': 'image_url',
                            'image_url': {
                                'url': f'data:image/jpeg;base64,{img_base64}'
                            }
                        })
                    converted.append({
                        'role': msg['role'],
                        'content': content_array if len(content_array) > 1 else content_array[0]['text'] if content_array else ''
                    })
                elif engine_type in ['openai_compat', 'deepseek', 'zhipu', 'ali']:
                    # OpenAI 兼容格式
                    content_array = []
                    if msg.get('content', '').strip():
                        content_array.append({
                            'type': 'text',
                            'text': msg['content']
                        })
                    for img_base64 in msg['images']:
                        # 检测图片类型
                        media_type = 'image/jpeg'  # 默认
                        try:
                            import base64
                            img_data = base64.b64decode(img_base64)
                            if img_data[:8] == b'\x89PNG\r\n\x1a\n':
                                media_type = 'image/png'
                            elif img_data[:3] == b'\xff\xd8\xff':
                                media_type = 'image/jpeg'
                        except:
                            pass
                        content_array.append({
                            'type': 'image_url',
                            'image_url': {
                                'url': f'data:{media_type};base64,{img_base64}'
                            }
                        })
                    converted.append({
                        'role': msg['role'],
                        'content': content_array
                    })
                else:
                    # 其他引擎，保留原样（可能不支持）
                    converted.append(msg)
            else:
                # 普通消息（无图片）
                if 'images' in msg:
                    # 移除 images 字段
                    msg_copy = {k: v for k, v in msg.items() if k != 'images'}
                    converted.append(msg_copy)
                else:
                    converted.append(msg)
        return converted

    # 检查是否包含图片但模型可能不支持
    has_images = any('images' in m for m in history.get('messages', []))
    if has_images and engine_type not in ['ollama', 'llama', 'openai_compat']:
        debug(f"警告: 当前引擎 {engine_type} 可能不支持图像输入，请使用支持多模态的模型")

    # 输出第一个用户消息的内容，用于调试图片是否解析成功
    for msg in history.get('messages', []):
        if msg.get('role') == 'user':
            if isinstance(msg.get('content'), list):
                debug(f"多模态消息包含 {len(msg['content'])} 部分")
            break

    # 详细调试信息（需要verbose=True才输出）
    verbose_debug(f"engine_type={engine_type}")
    verbose_debug(f"api={api}")
    verbose_debug(f"headers={headers}")
    verbose_debug(f"history={history}")

    # 工具调用配置
    tool_names = _get_user_config_item("tools", [], user_config)
    tool_defs = None
    if tool_names and isinstance(tool_names, list):
        from llm_engine.tools import get_tool_definitions, execute_tool
        tool_defs = get_tool_definitions(tool_names)
        if tool_defs:
            history["tools"] = tool_defs
            verbose_debug(f"tools={[t['function']['name'] for t in tool_defs]}")

    debug("===========>")

    # 发起请求（支持工具调用循环）
    base_dir = os.environ.get('LLM_FILE_DIR', os.getcwd())
    max_tool_rounds = _get_user_config_item("max_tool_rounds", 10, user_config)
    resp = None
    response_completed = False
    try:
        print(_roles['assistant'], end='', flush=True)

        for tool_round in range(max_tool_rounds + 1):
            # 每轮请求前转换多模态消息格式
            history['messages'] = convert_multimodal_messages(
                history['messages'], engine_type)
            resp = requests.post(api, json=history, headers=headers,
                                 stream=True, timeout=timeout)
            # 如果 400 且含图片，可能是模型不支持视觉，去掉图片重试
            if resp.status_code == 400:
                has_images = any(
                    isinstance(m.get('content'), list) and
                    any(isinstance(p, dict) and p.get('type') == 'image_url'
                        for p in m['content'])
                    for m in history.get('messages', [])
                )
                if has_images:
                    debug("模型可能不支持图片输入，去掉图片重试...")
                    for msg in history['messages']:
                        if isinstance(msg.get('content'), list):
                            text_parts = [
                                p['text'] for p in msg['content']
                                if isinstance(p, dict) and p.get('type') == 'text'
                            ]
                            msg['content'] = ' '.join(text_parts) if text_parts else ''
                    resp = requests.post(api, json=history, headers=headers,
                                         stream=True, timeout=timeout)
            resp.raise_for_status()

            content, tool_calls = _stream_response(resp, engine_type)

            if not tool_calls or not tool_defs:
                break

            # 有工具调用：执行工具并继续对话
            print()  # 换行

            # 将 assistant 的 tool_calls 消息加入历史
            assistant_msg = {"role": "assistant", "content": content or ""}
            if engine_type == 'ollama':
                # Ollama：arguments 保持 dict 格式
                ollama_tcs = []
                for tc in tool_calls:
                    args = tc['function']['arguments']
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    ollama_tcs.append({
                        'function': {'name': tc['function']['name'],
                                     'arguments': args}
                    })
                assistant_msg["tool_calls"] = ollama_tcs
            else:
                # OpenAI 兼容格式
                assistant_msg["tool_calls"] = tool_calls
            history["messages"].append(assistant_msg)

            # 逐个执行工具
            pending_images = []  # 收集图片，等所有 tool results 发完后再注入
            for tc in tool_calls:
                func_name = tc['function']['name']
                func_args = tc['function']['arguments']
                if isinstance(func_args, str):
                    try:
                        func_args = json.loads(func_args)
                    except json.JSONDecodeError:
                        func_args = {}

                debug(f"[Tool: {func_name}] {json.dumps(func_args, ensure_ascii=False)}")

                result = execute_tool(func_name, func_args, base_dir)

                # 检查是否为图片结果
                if isinstance(result, dict) and result.get('_image'):
                    text_result = result['text']
                    debug(f"[Result: {func_name}] {text_result}")

                    # 工具结果（文本说明）
                    tool_msg = {"role": "tool", "content": text_result}
                    if tc.get('id'):
                        tool_msg["tool_call_id"] = tc['id']
                    if engine_type == 'ollama':
                        tool_msg.pop("tool_call_id", None)
                    history["messages"].append(tool_msg)

                    # 暂存图片，稍后注入
                    pending_images.append(result['base64'])
                else:
                    # 普通文本结果
                    if isinstance(result, str):
                        preview = result[:200].replace('\n', '\\n')
                        if len(result) > 200:
                            preview += '...'
                    else:
                        preview = str(result)[:200]
                    debug(f"[Result: {func_name}] {preview}")

                    tool_msg = {"role": "tool", "content": result if isinstance(result, str) else str(result)}
                    if tc.get('id'):
                        tool_msg["tool_call_id"] = tc['id']
                    if engine_type == 'ollama':
                        tool_msg.pop("tool_call_id", None)
                    history["messages"].append(tool_msg)

            # 所有 tool results 发完后，注入图片到 user 消息中
            # 使用 images 字段统一存储，由 convert_multimodal_messages 在请求前转格式
            if pending_images:
                img_msg = {
                    "role": "user",
                    "content": "[Image from view_image tool]",
                    "images": pending_images
                }
                history["messages"].append(img_msg)

            verbose_debug(f"tool round {tool_round + 1} completed, continuing...")

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
        if hasattr(e, 'response') and e.response is not None:
            try:
                debug(f"Response body: {e.response.text[:500]}")
            except Exception:
                pass
    except Exception as e:
        print()
        debug(f"Unexpected error occurred: {e}")

    print(f"//updated at {time.asctime()} in {(time.time()-start_time):.1f} seconds", end='')
