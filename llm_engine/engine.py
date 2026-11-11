# -*- coding: utf-8 -*-
"""
LLM Engine - 处理.llm文件上下文并发送给LLM服务
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
import hashlib
import copy

from llm_engine.provider_spec import (
    apply_provider_defaults,
    build_api_url,
    build_model_query_url,
    get_config_root,
    get_legacy_user_config_paths,
    load_json_file,
    resolve_provider_runtime,
)

# SIGTERM 处理：收到信号时关闭流式连接并退出
_active_response = None

def _sigterm_handler(signum, frame):
    global _active_response
    if _active_response is not None:
        try:
            _active_response.close()
        except Exception:
            pass
    sys.exit(1)

signal.signal(signal.SIGTERM, _sigterm_handler)

# Python 2/3 兼容
if sys.version_info[0] == 2:
    import ConfigParser as configparser
else:
    import configparser

# 全局配置
_config = None
_verbose_mode = False
# debug 配置：False 关闭；'request' 仅打印原始请求报文；'full' 同时打印响应原始流（true 等价于 'full'）
_debug_mode = False
# stdout 是否停在未换行的 Assistant: 前缀上（debug 输出前需要先结束该行）
_assistant_line_open = False
_parse_diagnostics = {
    'orphan_lines': [],
}

# 角色前缀定义
_roles = {
    "system":    "System: ",
    "user":      "User: ",
    "assistant": "Assistant: ",
    "tool":      "Tool: ",
    "config":    "Configure: ",
}

# 常用前缀
_prefixes = {
    "comm":     "@##",
    "tmp_comm": "@//",
    "inc":      "@@inc ",
}

def _detect_role_line(line):
    """检测角色前缀，兼容全角冒号和冒号后无空格写法。"""
    # 优先使用标准前缀（兼容现有行为）
    for role_name, role_prefix in _roles.items():
        if line.startswith(role_prefix):
            return role_name, line[len(role_prefix):]

    # 宽松匹配：Role[:：][可选空格]content
    m = re.match(r'^(System|User|Assistant|Tool|Configure)\s*[:：]\s?(.*)$', line)
    if m:
        role_text = m.group(1).lower()
        content = m.group(2)
        return role_text, content

    return None, None

def _load_config():
    """加载配置文件

    配置优先级（从高到低）：
      1. 每个 .llm 文件中的 Configure: 行（运行时覆盖）
            2. 用户配置 ~/.config/llm-with-vim/config.json
            3. 兼容旧配置 ~/.config/contextforge/config.json、
               ~/.config/llm_engine/llm_engine.json（自动迁移）
      3. 包内置默认配置 default_config.json

    用户配置文件只需包含需要修改的部分（如 auth_keys），会与默认配置深度合并。
    也可通过 LLM_ENGINE_CONFIG 环境变量指定用户配置文件路径。
    """
    global _config
    if _config is None:
        # 先加载内置默认配置作为基础
        default_path = os.path.join(
            os.path.dirname(__file__), 'default_config.json')
        _config = load_json_file(default_path)
        if _config is None:
            print("Error loading default config: %s" % default_path, file=sys.stderr)
            sys.exit(1)

        # 旧配置自动迁移：新配置不存在且未用环境变量显式指定时，
        # 按新旧顺序找第一份旧配置拷贝到新路径
        # 迁移失败不覆盖任何文件，继续按旧路径读取（见 docs/contextforge_architecture_design.md 7.2）
        env_config_path = os.environ.get('LLM_ENGINE_CONFIG')
        if env_config_path:
            env_config_path = os.path.expanduser(env_config_path)
        legacy_paths = get_legacy_user_config_paths()
        new_path = os.path.join(get_config_root(), 'config.json')
        if not os.path.isfile(new_path) and not env_config_path:
            for legacy_path in legacy_paths:
                if not os.path.isfile(legacy_path):
                    continue
                try:
                    if not os.path.isdir(get_config_root()):
                        os.makedirs(get_config_root())
                    with open(legacy_path, 'rb') as src, open(new_path, 'wb') as dst:
                        dst.write(src.read())
                    print("@// 已自动迁移旧配置到 %s（原文件 %s 保留，确认无误后可删除）"
                          % (new_path, legacy_path))
                except Exception as e:
                    print("@// 旧配置自动迁移失败(%s)，继续直接读取旧路径" % e, file=sys.stderr)
                break

        # 先加载旧配置（列表靠后者优先），再加载新配置，最后允许显式环境变量覆盖
        user_config_paths = legacy_paths + [new_path]
        if env_config_path and env_config_path not in user_config_paths:
            user_config_paths.append(env_config_path)

        for user_config_path in user_config_paths:
            if os.path.isfile(user_config_path):
                user_cfg = load_json_file(user_config_path)
                if user_cfg:
                    _deep_merge(_config, user_cfg)

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

# 追加模式（跳过上下文重新输出，直接接收LLM响应）
_append_mode = '--append' in sys.argv

if _append_mode:
    sys.argv.remove('--append')

def debug(msg, noend=False):
    """输出调试信息到stdout（作为注释）
    追加模式下不输出，避免污染编辑器缓冲区"""
    global _assistant_line_open
    if _append_mode:
        return
    if not noend:
        # 本行输出会连带结束未换行的 Assistant: 前缀行
        _assistant_line_open = False
    if (noend):
        print(f"@// {msg}", end='')
    else:
        print(f"@// {msg}", flush=True)

def think(msg):
    debug(f"[think] {msg}");


def report_error(msg):
    """统一错误输出到 stderr，避免在追加模式下被 debug 抑制。"""
    if msg is None:
        return
    text = str(msg)
    if not text.endswith('\n'):
        text += '\n'
    sys.stderr.write(text)
    sys.stderr.flush()


def guide(msg, level='INFO'):
    """输出面向用户的会话内提示，始终以注释形式可见。"""
    if msg is None:
        return
    prefix = '@// %s: ' % level
    lines = str(msg).splitlines() or ['']
    for line in lines:
        print(prefix + line, flush=True)


def _reset_parse_diagnostics():
    global _parse_diagnostics
    _parse_diagnostics = {
        'orphan_lines': [],
    }


def _get_parse_diagnostics():
    return _parse_diagnostics


def _emit_starter_template_hint(engine_type='ollama', user_config=None):
    guide('you can start from this template and edit it:', 'HINT')
    print("@// ---- template start ----", flush=True)
    # 模板用当前生效配置生成，而不是硬编码示例：用户全局配置了什么就展示什么
    engine_type = _get_user_config_item("engine_type", engine_type, user_config)
    server_addr = _get_user_config_item("server_addr", "localhost", user_config)
    model = _get_user_config_item("model", "qwen2.5:0.5b", user_config)
    print("Configure: {'engine_type': '%s', 'server_addr': '%s', 'model': '%s', 'max_tokens': 1024, 'temperature': 1}" % (engine_type, server_addr, model), flush=True)
    print('System: You are a helpful assistant.', flush=True)
    print('User: 我应该怎么做？', flush=True)
    print('Assistant: ', flush=True)
    print('User: ', flush=True)
    print("@// ---- template end ----", flush=True)
    print("@// 想知道有哪些引擎、工具和当前生效配置？把 engine_type 设为 'TELLME' 再提交一次", flush=True)


_TELLME_CONFIG_KEYS = (
    'engine_type', 'server_addr', 'model', 'max_tokens', 'temperature',
    'repeat_penalty', 'top_p', 'keep_alive', 'thinking', 'stream',
    'max_tool_rounds', 'auth',
)


def _mask_secret(value):
    text = str(value)
    if len(text) <= 8:
        return '***'
    return text[:8] + '***'


def _emit_tellme_environment(user_config):
    """engine_type=TELLME 时的环境信息输出：纯本地查询，不访问网络。"""
    from llm_engine.provider_spec import (
        list_provider_specs, get_user_provider_dir)
    from llm_engine.tools import list_registered_tool_names

    print("@// === ContextForge 环境信息 ===", flush=True)
    print("@// 可用引擎（内置 + 用户目录 %s）：" % get_user_provider_dir(), flush=True)
    for spec in list_provider_specs():
        provider_id = spec.get('id', '?')
        display_name = spec.get('display_name', provider_id)
        auth_type = spec.get('auth', {}).get('type', 'none')
        auth_desc = ('免鉴权' if auth_type in (None, '', 'none')
                     else '需%s' % auth_type)
        default_model = spec.get('defaults', {}).get('model', '')
        line = "@//   %-14s %-20s %-8s" % (provider_id, display_name, auth_desc)
        if default_model:
            line += "  默认模型 %s" % default_model
        print(line, flush=True)
    print("@// 可用工具：%s" % ' '.join(list_registered_tool_names()), flush=True)
    print("@//   （把工具名写进 Configure 的 tools 列表即启用）", flush=True)
    print("@// 当前生效配置（默认+用户+本文件三层合并）：", flush=True)
    for key in _TELLME_CONFIG_KEYS:
        default = 'ollama' if key == 'engine_type' else None
        value = _get_user_config_item(key, default, user_config)
        if value is None:
            continue
        if key in ('auth', 'api_key'):
            value = _mask_secret(value)
        print("@//   %s = %s" % (key, value), flush=True)
    print("@// 想知道服务器上有什么模型？把 model 设为 'TELLME' 再提交一次", flush=True)
    print("@// 配置说明见 README.md 的 Configure 与全局配置两节", flush=True)

def verbose_debug(msg):
    """输出详细调试信息（需要verbose=True才输出）"""
    if _verbose_mode:
        debug(msg)


def _resolve_debug_mode(user_config):
    """解析 debug 配置，返回 False / 'request' / 'full'。

    - False：关闭
    - 'request'：仅打印发送给 LLM 的原始请求报文
    - 'full'：同时打印响应的原始流与错误响应体（true/1/on 等布尔真值等价于 'full'）

    优先级：环境变量 LLM_ENGINE_DEBUG > Configure 行 > 全局 config > 默认 False
    """
    def _normalize(value):
        if isinstance(value, str):
            text = value.strip().lower()
            if text == 'request':
                return 'request'
            if text == 'full' or text in ('1', 'true', 'yes', 'on'):
                return 'full'
            return False
        return 'full' if value else False

    env_value = (os.environ.get('LLM_ENGINE_DEBUG') or '').strip()
    if env_value:
        return _normalize(env_value)

    raw = _get_user_config_item("debug", None, user_config)
    if raw is None:
        raw = _config.get("default_config", {}).get("debug", False)
    return _normalize(raw)


def _mask_auth_headers(headers):
    """复制 headers 并脱敏认证字段，避免密钥被写入可分享的 .llm 文件。"""
    masked = {}
    for key, value in (headers or {}).items():
        text = str(value)
        if key.lower() in ('authorization', 'api-key', 'x-api-key') and text:
            masked[key] = text[:16] + '***' if len(text) > 16 else '***'
        else:
            masked[key] = value
    return masked


def _condense_debug_b64(value, keep=64):
    """截断 base64 数据用于调试展示，避免撑爆输出。"""
    if isinstance(value, str) and len(value) > keep:
        return value[:keep] + '...(%d chars omitted)' % len(value)
    return value


def _condense_debug_payload(obj):
    """递归压缩请求中的图片 base64 数据，文本内容原样保留。"""
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key == 'images' and isinstance(value, list):
                result[key] = [_condense_debug_b64(v) for v in value]
            elif key == 'url' and isinstance(value, str) and value.startswith('data:'):
                result[key] = _condense_debug_b64(value)
            else:
                result[key] = _condense_debug_payload(value)
        return result
    if isinstance(obj, list):
        return [_condense_debug_payload(v) for v in obj]
    return obj


def debug_dump(msg=''):
    """输出原始报文调试信息（显式开启 debug 配置时输出）。

    与 debug() 不同：debug() 在 --append 模式下静默以避免污染编辑器缓冲区，
    而这里是用户显式要求的调试输出，正常/追加模式下均应可见。
    """
    global _assistant_line_open
    if _assistant_line_open:
        print(flush=True)
        _assistant_line_open = False
    if msg:
        print(f"@// [debug] {msg}", flush=True)
    else:
        print("@// [debug]", flush=True)


def _debug_dump_request(api, headers, payload_text, payload_obj, trace_label=''):
    """以 @// 注释形式输出一次请求的完整原始报文。"""
    label = trace_label or 'request'
    debug_dump(f"===== {label} request ({len(payload_text)} bytes) =====")
    debug_dump(f"POST {api}")
    debug_dump("headers: %s" % json.dumps(_mask_auth_headers(headers), ensure_ascii=False))
    for line in json.dumps(_condense_debug_payload(payload_obj), ensure_ascii=False, indent=2).splitlines():
        debug_dump(line)
    debug_dump(f"===== end {label} request =====")


def _debug_dump_error_body(resp, body):
    """以 @// 注释形式输出 HTTP 错误响应的完整原始内容。"""
    debug_dump("===== raw error response =====")
    debug_dump(f"HTTP {resp.status_code} {resp.reason}")
    content_type = resp.headers.get('Content-Type', '')
    if content_type:
        debug_dump(f"content-type: {content_type}")
    for line in body.splitlines() or ['']:
        if len(line) > 300:
            line = line[:300] + '...(%d chars)' % len(line)
        debug_dump(f"<< {line}")
    debug_dump("===== end raw error response =====")


def _debug_merge_top_level(result, data, skip_keys):
    """聚合响应时合并顶层字段：跳过指定键；空值不写入（后到的有效值覆盖）。"""
    for key, value in data.items():
        if key in skip_keys:
            continue
        if value is None or value == '' or value == {} or value == []:
            continue
        result[key] = value


def _aggregate_sse_debug(lines):
    """将 OpenAI 兼容 SSE 流分片重组为等价的完整响应对象。"""
    result = {}
    message = {'role': 'assistant', 'content': ''}
    content_parts = []
    reasoning_parts = []
    tool_calls = {}
    parsed = 0

    for text in lines:
        if not text.startswith('data:'):
            continue
        payload = text.split('data:', 1)[-1].strip()
        if payload == '[DONE]':
            continue
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        parsed += 1

        for key in ('id', 'object', 'created', 'model'):
            if key not in result and data.get(key) is not None:
                result[key] = data[key]

        choices = data.get('choices') or []
        if choices and isinstance(choices[0], dict):
            choice = choices[0]
            delta = choice.get('delta') or {}
            if delta.get('role'):
                message['role'] = delta['role']
            if isinstance(delta.get('content'), str):
                content_parts.append(delta['content'])
            reasoning = _parse_reasoning_delta(delta)
            if reasoning:
                reasoning_parts.append(reasoning)
            for tc in delta.get('tool_calls') or []:
                if not isinstance(tc, dict):
                    continue
                idx = tc.get('index', 0)
                acc = tool_calls.setdefault(idx, {
                    'id': '', 'type': 'function',
                    'function': {'name': '', 'arguments': ''}})
                if tc.get('id'):
                    acc['id'] = tc['id']
                func = tc.get('function') or {}
                if func.get('name'):
                    acc['function']['name'] += func['name']
                if isinstance(func.get('arguments'), str):
                    acc['function']['arguments'] += func['arguments']
            if choice.get('finish_reason'):
                result['finish_reason'] = choice['finish_reason']

        if isinstance(data.get('usage'), dict) and data['usage']:
            result['usage'] = data['usage']

    if not parsed:
        return None

    message['content'] = ''.join(content_parts)
    if reasoning_parts:
        message['reasoning_content'] = ''.join(reasoning_parts)
    if tool_calls:
        message['tool_calls'] = [tool_calls[i] for i in sorted(tool_calls)]
    result['message'] = message
    return result


def _aggregate_ollama_debug(lines):
    """将 Ollama NDJSON 流分片重组为等价的完整响应对象（末块统计字段保留）。"""
    result = {}
    message = {'role': 'assistant', 'content': ''}
    content_parts = []
    reasoning_parts = []
    tool_calls = None
    parsed = 0

    for text in lines:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        parsed += 1

        msg = data.get('message')
        if isinstance(msg, dict):
            if msg.get('role'):
                message['role'] = msg['role']
            if isinstance(msg.get('content'), str):
                content_parts.append(msg['content'])
            reasoning = _parse_reasoning_delta(msg)
            if reasoning:
                reasoning_parts.append(reasoning)
            if msg.get('tool_calls'):
                tool_calls = msg['tool_calls']

        _debug_merge_top_level(result, data, skip_keys=('message',))

    if not parsed:
        return None

    message['content'] = ''.join(content_parts)
    if reasoning_parts:
        message['reasoning_content'] = ''.join(reasoning_parts)
    if tool_calls:
        message['tool_calls'] = tool_calls
    result['message'] = message
    return result


def _aggregate_json_full_debug(lines):
    """将 json_full 流（每行一个完整响应对象）聚合为最终响应。"""
    result = {}
    content_parts = []
    parsed = 0

    for text in lines:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict) or 'choices' not in data:
            continue
        parsed += 1

        choices = data.get('choices') or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get('message') or {}
            if isinstance(msg.get('content'), str):
                content_parts.append(msg.get('content'))

        _debug_merge_top_level(result, data, skip_keys=('choices',))

    if not parsed:
        return None

    result['message'] = {'role': 'assistant', 'content': ''.join(content_parts)}
    return result


def _aggregate_debug_response(lines, response_mode):
    """把流式响应的原始行聚合成等价的完整响应对象；无法结构化时返回 None。"""
    if response_mode == 'sse_openai_delta':
        return _aggregate_sse_debug(lines)
    if response_mode == 'json_line_ollama':
        return _aggregate_ollama_debug(lines)
    if response_mode == 'json_full':
        return _aggregate_json_full_debug(lines)
    return None


def _get_session_allowed_keys(provider_spec):
    allowed = set([
        'engine_type',
        'server_addr',
        'server_port',
        'model',
        'temperature',
        'max_tokens',
        'connect_timeout',
        'read_timeout',
        'tools',
        'max_tool_rounds',
        'thinking',
        'verbose',
        'debug',
        'auth',
        'keep_alive',
        'stream',
    ])
    allowed.update(provider_spec.get('defaults', {}).keys())
    overrides = provider_spec.get('overrides', {})
    allowed.update(overrides.get('allowed_in_session', []))
    return allowed


def _warn_unknown_user_config_fields(user_config, provider_spec):
    if not user_config or not isinstance(user_config, dict):
        return

    allowed = _get_session_allowed_keys(provider_spec)
    unknown = sorted(key for key in user_config.keys() if key not in allowed)
    if not unknown:
        return

    guide('unknown Configure fields ignored: %s' % ', '.join(unknown), 'WARN')
    guide('allowed session fields: %s' % ', '.join(sorted(allowed)), 'HINT')


def _is_model_not_found_error(message):
    if not message:
        return False
    text = str(message).lower()
    patterns = [
        'model not found',
        'unknown model',
        'does not exist',
        'no such model',
        'failed to find model',
        'try pulling it first',
        'manifest unknown',
    ]
    if 'model' not in text:
        return False
    return any(pattern in text for pattern in patterns)


def _fetch_available_models(model_query_url, headers, timeout, protocol):
    """查询服务器可用模型列表；model_query_url 缺失时返回空列表，其它异常直接抛出由调用方处理。"""
    if not model_query_url:
        return []
    resp = requests.get(model_query_url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if protocol == 'ollama_native':
        return [m['name'] for m in data.get('models', []) if isinstance(m, dict) and m.get('name')]
    return [m['id'] for m in data.get('data', []) if isinstance(m, dict) and m.get('id')]


def _guide_model_suggestions(model_name, provider_runtime, timeout):
    try:
        models = _fetch_available_models(
            provider_runtime.get('model_query_url'),
            provider_runtime.get('headers', {}),
            timeout,
            provider_runtime.get('protocol', 'openai_compat'),
        )
    except Exception:
        models = []
    if not models:
        guide('model not found: %s' % model_name, 'ERROR')
        guide('current provider does not expose a usable model list endpoint', 'HINT')
        return

    protocol = provider_runtime.get('protocol', 'openai_compat')
    show_models = models if protocol == 'ollama_native' else models[:20]
    guide('model not found: %s' % model_name, 'ERROR')
    guide('server supports %d models' % len(models), 'INFO')
    if protocol == 'ollama_native':
        guide('available models:', 'HINT')
        for model in show_models:
            guide('  %s' % model, 'HINT')
    else:
        guide('try one of: %s' % ', '.join(show_models), 'HINT')
    guide("Configure: {'engine_type': '%s', 'model': '%s'}" % (
        provider_runtime.get('provider_id', 'openai_compat'),
        show_models[0] if show_models else model_name,
    ), 'HINT')


def _validate_history_before_request(history, user_config=None):
    """请求前校验：至少应包含一条 User 消息。"""
    messages = history.get('messages', []) if isinstance(history, dict) else []
    has_user = any(isinstance(msg, dict) and msg.get('role') == 'user' for msg in messages)

    diagnostics = _get_parse_diagnostics()
    orphan_lines = diagnostics.get('orphan_lines', [])
    if orphan_lines:
        sample = ', '.join('line %d' % ln for ln, _ in orphan_lines[:3])
        guide('found text outside any role block (%s)' % sample, 'ERROR')
        guide('every content line should be under System/User/Assistant/Tool/Configure role', 'HINT')
        _emit_starter_template_hint('ollama', user_config)
        report_error('request aborted: invalid context lines outside role blocks')
        return False

    if has_user:
        return True

    guide('no User message found in context', 'ERROR')
    guide("write your question using a role prefix, e.g. User: 我应该怎么做？", 'HINT')
    _emit_starter_template_hint('ollama', user_config)
    report_error('request aborted: no User message found')
    return False

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


def _normalize_content_text(text):
    """对消息文本做最小归一化：仅统一换行风格，不裁剪首尾空白。"""
    if text is None:
        return ''
    if not isinstance(text, str):
        text = str(text)
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _stable_json_dumps(obj):
    """稳定 JSON 序列化，保证同输入同输出。"""
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        allow_nan=False,
    )


def _sha256_text(text):
    """计算 UTF-8 文本的 SHA-256。"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _post_stream_request(api, payload_obj, headers, timeout, trace_label=''):
    """使用稳定 JSON 字节串发起流式请求，返回 (resp, payload_hash)。"""
    payload_text = _stable_json_dumps(payload_obj)
    payload_hash = _sha256_text(payload_text)
    if trace_label:
        verbose_debug(f"{trace_label}.payload_hash={payload_hash}")
    if _debug_mode:
        _debug_dump_request(api, headers, payload_text, payload_obj, trace_label)
    resp = requests.post(
        api,
        data=payload_text.encode('utf-8'),
        headers=headers,
        stream=True,
        timeout=timeout,
    )
    if _debug_mode:
        debug_dump(f"{trace_label or 'request'} response: HTTP {resp.status_code}")
    return resp, payload_hash


def _format_tool_role_content(func_name, func_args, result_text, tool_call_id=''):
    """生成 Tool 角色的稳定编码文本（单行 JSON，便于编辑与重放）。"""
    payload = {
        'v': 1,
        'name': func_name,
        'arguments': func_args if isinstance(func_args, dict) else str(func_args),
        'result': result_text if isinstance(result_text, str) else str(result_text),
    }
    if tool_call_id:
        payload['id'] = tool_call_id
    return _stable_json_dumps(payload)


def _decode_tool_role_content(content):
    """解析 Tool 角色编码，提取可提交给模型的 tool content。"""
    normalized = _normalize_content_text(content)
    candidate = normalized.strip()
    if not candidate:
        return ''

    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return normalized

    if not isinstance(data, dict):
        return normalized
    if data.get('v') != 1 or 'result' not in data:
        return normalized

    result = data.get('result', '')
    return result if isinstance(result, str) else str(result)

def _add_msg(req, role, content, images=None):
    """给请求增加某个角色的消息，支持多模态"""
    if not content and not images:
        return

    msg = {"role": role}

    normalized_content = _normalize_content_text(content)

    if role == 'tool':
        msg['content'] = _decode_tool_role_content(normalized_content)
        req['messages'].append(msg)
        return

    if images:
        # 多模态消息格式（Ollama 风格）
        msg["content"] = normalized_content
        msg["images"] = [img['base64'] for img in images]
    else:
        msg["content"] = normalized_content

    req['messages'].append(msg)


def _parse_input():
    """
    处理stdin的输入信息。返回history, config。

    核心设计：
    - 所有文件（主文件和头文件）都一行一行顺序处理
    - 维护当前角色状态，延续内容追加到当前角色
    - 遇到@@inc时压栈，处理完头文件后弹栈继续，保持角色状态连续
    - 支持 $$图片路径$$ 语法嵌入多模态内容
    """
    global _config
    _reset_parse_diagnostics()
    history = copy.deepcopy(_config["request_template"])
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
                    output_lines.append(f"@// Image: {img['full_path']}\n")

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
            # 包含文件处理完毕，flush当前角色防止跨文件延续
            flush_role()
            current_role = 'none'
            continue

        line = current_lines[line_idx]
        stack[-1] = (current_lines, line_idx + 1, base_dir, depth, is_main_file)

        # 处理不同类型的行
        if line.startswith(_prefixes['tmp_comm']):          # 临时注释/调试信息，忽略
            continue

        elif line.startswith(_prefixes['comm']):             # 长久注释
            flush_role()
            if is_main_file:
                output_lines.append(line)
            current_role = 'none'

        elif line.startswith(_prefixes['inc']):             # 头文件原语
            flush_role()
            if is_main_file:
                output_lines.append(line)
            current_role = 'none'

            # 检查深度限制
            if depth >= MAX_DEPTH:
                debug(f"{_prefixes['inc']}: maximum nesting depth ({MAX_DEPTH}) exceeded")
                continue

            # 解析文件名
            parts = line.strip().split(None, 1)
            if len(parts) < 2:
                debug(f"{_prefixes['inc']}: Invalid directive: {line.strip()}")
                continue

            filename = parts[1].strip()

            # 验证文件名
            if os.path.isabs(filename) or '..' in filename:
                debug(f"{_prefixes['inc']}: invalid path: {filename}")
                continue

            # 构建完整路径
            file_path = os.path.join(base_dir, filename) if base_dir else filename
            file_path = os.path.normpath(file_path)
            if '..' in file_path:
                debug(f"{_prefixes['inc']}: path traversal not allowed: {filename}")
                continue

            # 读取被包含的文件
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except (FileNotFoundError, IOError, UnicodeDecodeError) as e:
                debug(f"{_prefixes['inc']}: error reading {filename}: {e}")
                continue

            # 获取被包含文件的目录
            file_dir = os.path.dirname(filename)
            new_base_dir = file_dir if file_dir else base_dir

            # 压栈处理头文件
            inc_lines = content.splitlines(keepends=True)
            stack.append((inc_lines, 0, new_base_dir, depth + 1, False))

        else:                                   # 普通内容行
            # 检查是否是新角色
            found_role, content_line = _detect_role_line(line)

            if found_role:
                # 新角色，提交当前角色内容
                flush_role()
                current_role = found_role

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
                            output_lines.append(f"@// Image: {img['full_path']}\n")
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
                        if current_role == 'none' and line.strip():
                            _parse_diagnostics['orphan_lines'].append((line_idx + 1, line.rstrip('\n')))
                        output_line(is_main_file, line)

    # 所有文件处理完毕，如果主文件没有Config但有user_config，插入到开头
    if not main_file_has_config and user_config:
        output_lines.insert(0, _roles['config'] + user_config + '\n')

    # 输出所有收集的行（保留原始输入，但在图片后添加注释）
    # 追加模式下不重新输出上下文，仅收集对话历史并发送给LLM
    if not _append_mode:
        sys.stdout.write(''.join(output_lines))
        sys.stdout.flush()

    if user_config:
        try:
            import ast
            try:
                uc = json.loads(user_config)
            except json.JSONDecodeError:
                try:
                    uc = ast.literal_eval(user_config)
                except (ValueError, SyntaxError, MemoryError, RecursionError):
                    # 兼容单引号 dict 混用 JSON 风格布尔/空值（true/false/null）
                    normalized = re.sub(
                        r'\b(true|false|null)\b',
                        lambda m: {'true': 'True', 'false': 'False', 'null': 'None'}[m.group(1)],
                        user_config)
                    uc = ast.literal_eval(normalized)

            if not isinstance(uc, dict):
                raise ValueError("Configuration must be a dictionary/object")
            return history, uc
        except (json.JSONDecodeError, ValueError, SyntaxError) as e:
            debug(f"Invalid user config: {user_config}")
            debug(f"Config parse error: {type(e).__name__}: {e}")
            if re.search(r'(^|\n)\s*(System|User|Assistant|Configure)\s*[:：]', user_config):
                debug("Hint: Configure 区块中混入了角色行。请确认角色前缀格式正确，并确保 Configure 只包含字典内容。")
            else:
                debug("Configuration must be in JSON format like {\"key\": \"value\"} or Python dict format like {'key': 'value'}")

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


def _parse_reasoning_delta(delta):
    """从流式 delta 中提取 reasoning/thinking 文本。"""
    if not isinstance(delta, dict):
        return ''

    candidates = [
        delta.get('reasoning_content'),
        delta.get('thinking'),
        delta.get('reasoning'),
        delta.get('think'),
    ]

    parts = []
    for item in candidates:
        if not item:
            continue
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            for key in ('content', 'text', 'reasoning_content'):
                value = item.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)
        elif isinstance(item, list):
            for node in item:
                if isinstance(node, str) and node:
                    parts.append(node)
                elif isinstance(node, dict):
                    for key in ('content', 'text'):
                        value = node.get(key)
                        if isinstance(value, str) and value:
                            parts.append(value)

    return ''.join(parts)


def _emit_thinking_stream(state, chunk, final=False):
    """按流式 chunk 输出 thinking，尽量按行合并零碎片段。"""
    if not state:
        return

    if chunk:
        state['buffer'] += chunk

    buffer = state['buffer']
    while True:
        newline_pos = buffer.find('\n')
        if newline_pos < 0:
            break
        line = buffer[:newline_pos]
        if not state['started']:
            debug('')
            state['started'] = True
        if line:
            think(f"{line}")
        else:
            think("")
        buffer = buffer[newline_pos + 1:]

    state['buffer'] = buffer

    if final and state['buffer']:
        if not state['started']:
            print('', flush=True)
            state['started'] = True
        think(f"{state['buffer']}")
        state['buffer'] = ''


def _stream_response(resp, response_mode, thinking_mode=False):
    """
    流式解析响应，实时输出文本内容，同时收集工具调用信息。
    返回 (content_text, tool_calls_list)。
    tool_calls 格式: [{'id': str, 'type': 'function',
                       'function': {'name': str, 'arguments': str}}]
    """
    content_parts = []
    # 累积工具调用: index -> {'id', 'type', 'function': {'name', 'arguments'}}
    tool_calls_acc = {}
    thinking_state = {'buffer': '', 'started': False} if thinking_mode else None

    # 'full' 模式下收集原始响应行，流结束（含异常中断）后聚合成完整响应一次性输出
    debug_raw_lines = []
    capture_raw = (_debug_mode == 'full')

    def capture_debug_line(line):
        if not capture_raw or not line:
            return
        try:
            decoded = line.decode('utf-8')
        except UnicodeDecodeError:
            decoded = '<binary %d bytes>' % len(line)
        debug_raw_lines.append(decoded)

    def flush_debug_raw():
        if not debug_raw_lines:
            return
        print()  # 结束未换行的内容输出，再打印调试信息
        aggregated = _aggregate_debug_response(debug_raw_lines, response_mode)
        if aggregated is not None:
            total_bytes = sum(len(text) for text in debug_raw_lines)
            debug_dump(f"===== response ({response_mode}, {len(debug_raw_lines)} lines, {total_bytes} bytes, aggregated) =====")
            for text in json.dumps(aggregated, ensure_ascii=False, indent=2).splitlines():
                debug_dump(f"<< {text}")
            debug_dump("===== end response =====")
        else:
            # 无法结构化聚合（如 raw_lines 模式或非 JSON 内容），回退为逐行输出
            debug_dump(f"===== raw response ({response_mode}, {len(debug_raw_lines)} lines) =====")
            for decoded in debug_raw_lines:
                if len(decoded) > 300:
                    decoded = decoded[:300] + '...(%d chars)' % len(decoded)
                debug_dump(f"<< {decoded}")
            debug_dump("===== end raw response =====")

    def iter_debug_lines():
        """包裹 resp.iter_lines()：捕获原始行，并保证流结束/异常中断时输出调试信息。"""
        try:
            for line in resp.iter_lines():
                capture_debug_line(line)
                yield line
        finally:
            flush_debug_raw()

    if response_mode == 'json_line_ollama':
        for line in iter_debug_lines():
            if not line:
                continue
            try:
                data = json.loads(line.decode('utf-8'))
                message = data.get('message', {})
                c = message.get('content', '')
                if c:
                    print(c, end='', flush=True)
                    content_parts.append(c)
                reasoning = _parse_reasoning_delta(message)
                if reasoning:
                    _emit_thinking_stream(thinking_state, reasoning)
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

    elif response_mode == 'raw_lines':
        for line in iter_debug_lines():
            if line:
                try:
                    decoded = line.decode('utf-8')
                    print(decoded)
                    content_parts.append(decoded + '\n')
                except UnicodeDecodeError:
                    continue

    elif response_mode == 'json_full':
        for line in iter_debug_lines():
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    if 'choices' in data and data['choices']:
                        message = data['choices'][0].get('message', {})
                        c = message.get('content', '')
                        if c:
                            print(c, end='', flush=True)
                            content_parts.append(c)
                        reasoning = _parse_reasoning_delta(message)
                        if reasoning:
                            _emit_thinking_stream(thinking_state, reasoning)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

    else:
        # OpenAI 兼容 SSE 格式 (deepseek, zhipu, ali, openai_compat)
        for line in iter_debug_lines():
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

                reasoning = _parse_reasoning_delta(delta)
                if reasoning:
                    _emit_thinking_stream(thinking_state, reasoning)

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

    _emit_thinking_stream(thinking_state, '', final=True)

    full_content = ''.join(content_parts)
    tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc.keys())]
    return full_content, tool_calls


def answer():
    """主函数：处理输入并发送给LLM"""
    global _config, _verbose_mode, _debug_mode, _assistant_line_open
    _load_config()

    start_time = time.time()

    # 处理输入
    history, user_config = _parse_input()

    # TELLME 环境查询：engine_type 为 TELLME 时输出环境清单后退出，不访问网络
    if _get_user_config_item("engine_type", "ollama", user_config) == 'TELLME':
        _emit_tellme_environment(user_config)
        sys.exit(0)

    if not _validate_history_before_request(history, user_config):
        sys.exit(2)

    # 获取verbose配置（尽早获取，以便后续调试信息能正确输出）
    _verbose_mode = _get_user_config_item("verbose", False, user_config)
    # debug 配置开启时自动启用 verbose，输出更多上下文信息
    _debug_mode = _resolve_debug_mode(user_config)
    if _debug_mode and not _verbose_mode:
        _verbose_mode = True

    # 组合配置
    base_config = copy.deepcopy(_config['default_config'])
    provider_id = _get_user_config_item("engine_type", "ollama", user_config)
    provider_runtime = resolve_provider_runtime(provider_id, base_config, _config, session_config=user_config)
    provider_spec = provider_runtime['spec']
    engine_type = provider_runtime['provider_id']
    response_mode = provider_runtime['response_mode']
    protocol = provider_runtime['protocol']
    common_config = provider_runtime['runtime_config']
    for key in common_config.keys():
        common_config[key] = _get_user_config_item(key, common_config[key], user_config)
    common_config = apply_provider_defaults(provider_spec, common_config)
    # 用户/全局配置可能修改 server_addr/server_port，重建 API URL（初始 URL 仅基于 default_config）
    provider_runtime['api_url'] = build_api_url(provider_spec, common_config)
    provider_runtime['model_query_url'] = build_model_query_url(provider_spec, common_config)
    server_addr = common_config.get('server_addr', provider_spec.get('endpoint', {}).get('default_host', 'localhost'))
    thinking_mode = _get_user_config_item("thinking", common_config.get('thinking', False), user_config)
    if protocol == 'ollama_native':
        keep_alive = _get_user_config_item("keep_alive", common_config.get('keep_alive', 60), user_config)

    # API请求头部（spec 负责默认认证方式）
    headers = provider_runtime['headers']
    _warn_unknown_user_config_fields(user_config, provider_spec)

    # 获取超时配置
    connect_timeout = common_config.get('connect_timeout', 30)
    read_timeout = common_config.get('read_timeout', 1800)
    timeout = (connect_timeout, read_timeout)

    api = provider_runtime['api_url']

    # 如果 model 为 "TELLME"，查询可用模型列表（endpoint 由 provider 描述的 model_query 决定）
    if common_config['model'] == 'TELLME':
        try:
            models = _fetch_available_models(
                provider_runtime.get('model_query_url'), headers, timeout, protocol)
        except Exception as e:
            print(f"@// 查询模型失败: {e}")
            sys.exit(0)

        if models:
            print(f"@// 可用模型列表 (共 {len(models)} 个):")
            for m in models:
                print(f"@//   {m}")
            print("@// 请将 Configure 中的 model 设置为上述模型之一")
        else:
            print("@// 未找到可用模型")
        sys.exit(0)

    # 没有给用户配置的生成一个
    if not user_config:
        user_config = common_config.copy()
        user_config["engine_type"] = engine_type
        user_config["server_addr"] = server_addr
        if protocol == 'ollama_native':
            user_config["keep_alive"] = keep_alive
        debug(f"{_roles['config']} {user_config}")

    # 根据配置完善请求记录（只导入 API 认可的请求参数）
    _internal_keys = {'connect_timeout', 'read_timeout', 'verbose', 'debug',
                       'tools', 'max_tool_rounds', 'thinking'}
    for key in common_config.keys():
        if key not in _internal_keys:
            history[key] = common_config[key]

    # 明确告知引擎是否启用 thinking，避免默认行为导致的性能问题
    # 注意：不是所有引擎都支持，但 ollama 需要 think: false 来真正关闭 thinking
    if thinking_mode:
        history['think'] = True
        if protocol != 'ollama_native':
            history['reasoning'] = {'enabled': True}
    else:
        # 明确关闭 thinking，避免模型进行不必要的思考
        history['think'] = False

    if protocol == 'ollama_native':
        history["keep_alive"] = keep_alive
    history["stream"] = bool(common_config.get("stream", True))

    # 处理多模态消息格式转换
    def convert_multimodal_messages(messages, engine_type):
        """根据引擎类型转换消息格式"""
        converted = []
        for msg in messages:
            if msg.get('role') == 'user' and 'images' in msg and msg['images']:
                # 有图片的消息
                if protocol == 'ollama_native':
                    # Ollama 格式: content + images 数组
                    converted.append({
                        'role': msg['role'],
                        'content': msg.get('content', ''),
                        'images': msg['images']
                    })
                elif protocol in ['openai_compat', 'raw_lines']:
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
    if has_images and not provider_spec.get('features', {}).get('vision', False):
        debug(f"警告: 当前引擎 {engine_type} 可能不支持图像输入，请使用支持多模态的模型")

    # 输出第一个用户消息的内容，用于调试图片是否解析成功
    for msg in history.get('messages', []):
        if msg.get('role') == 'user':
            if isinstance(msg.get('content'), list):
                debug(f"多模态消息包含 {len(msg['content'])} 部分")
            break

    try:
        context_snapshot = {'messages': history.get('messages', [])}
        context_hash = _sha256_text(_stable_json_dumps(context_snapshot))
        verbose_debug(f"context_hash={context_hash}")
    except (TypeError, ValueError) as e:
        verbose_debug(f"context_hash_unavailable={e}")

    # 详细调试信息（需要verbose=True才输出）
    verbose_debug(f"engine_type={engine_type}")
    verbose_debug(f"api={api}")
    verbose_debug(f"headers={_mask_auth_headers(headers)}")
    verbose_debug(f"history={history}")

    # 工具调用配置
    tool_names = _get_user_config_item("tools", [], user_config)
    tool_defs = None
    if tool_names and isinstance(tool_names, list):
        from llm_engine.tools import (
            get_tool_definitions,
            execute_tool,
            get_unknown_tool_names,
            list_registered_tool_names,
        )
        unknown_tool_names = get_unknown_tool_names(tool_names)
        if unknown_tool_names:
            guide('unknown tools ignored: %s' % ', '.join(unknown_tool_names), 'WARN')
            guide('valid tools: %s' % ', '.join(list_registered_tool_names()), 'HINT')
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
    request_failed = False
    assistant_prefix_open = False
    try:
        print(_roles['assistant'], end='', flush=True)
        assistant_prefix_open = True
        _assistant_line_open = True

        for tool_round in range(max_tool_rounds + 1):
            # 每轮请求前转换多模态消息格式
            history['messages'] = convert_multimodal_messages(
                history['messages'], engine_type)
            resp, _payload_hash = _post_stream_request(
                api,
                history,
                headers,
                timeout,
                trace_label=f"round{tool_round + 1}",
            )
            _active_response = resp
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
                    resp, _payload_hash = _post_stream_request(
                        api,
                        history,
                        headers,
                        timeout,
                        trace_label=f"round{tool_round + 1}.retry_no_image",
                    )
                    _active_response = resp
            resp.raise_for_status()

            content, tool_calls = _stream_response(resp, response_mode, thinking_mode)

            if not tool_calls or not tool_defs:
                break

            # 有工具调用：执行工具并继续对话
            print()  # 换行

            # 将 assistant 的 tool_calls 消息加入历史
            assistant_msg = {"role": "assistant", "content": content or ""}
            if protocol == 'ollama_native':
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

                    tool_role_content = _format_tool_role_content(
                        func_name,
                        func_args,
                        text_result,
                        tc.get('id', ''),
                    )
                    print(_roles['tool'] + tool_role_content)

                    # 工具结果（文本说明）
                    tool_msg = {"role": "tool", "content": text_result}
                    if tc.get('id'):
                        tool_msg["tool_call_id"] = tc['id']
                    if protocol == 'ollama_native':
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

                    result_text = result if isinstance(result, str) else str(result)
                    tool_role_content = _format_tool_role_content(
                        func_name,
                        func_args,
                        result_text,
                        tc.get('id', ''),
                    )
                    print(_roles['tool'] + tool_role_content)

                    tool_msg = {"role": "tool", "content": result_text}
                    if tc.get('id'):
                        tool_msg["tool_call_id"] = tc['id']
                    if protocol == 'ollama_native':
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
    except requests.exceptions.HTTPError as e:
        request_failed = True
        if assistant_prefix_open:
            print('', flush=True)
            assistant_prefix_open = False
        debug(f"{os.linesep}HTTP error occurred: {e}")
        report_error(f"HTTP error occurred: {e}")
        if _is_model_not_found_error(e):
            _guide_model_suggestions(common_config.get('model', ''), provider_runtime, timeout)
        if hasattr(e, 'response') and e.response is not None:
            try:
                body = e.response.text
                if _debug_mode == 'full':
                    _debug_dump_error_body(e.response, body)
                debug(f"Response body: {body[:500]}")
                report_error(f"Response body: {body[:500]}")
                if _is_model_not_found_error(body):
                    _guide_model_suggestions(common_config.get('model', ''), provider_runtime, timeout)
                elif provider_runtime.get('protocol') == 'ollama_native' and e.response.status_code in (400, 404):
                    _guide_model_suggestions(common_config.get('model', ''), provider_runtime, timeout)
            except Exception:
                pass
    except Exception as e:
        request_failed = True
        if assistant_prefix_open:
            print('', flush=True)
            assistant_prefix_open = False
        debug(f"{os.linesep} request fail: {e}")
        report_error(f"request fail: {e}")
    finally:
        _active_response = None

    debug(f"updated at {time.asctime()} in {(time.time()-start_time):.1f} seconds", noend=True)
    if request_failed:
        sys.exit(2)
