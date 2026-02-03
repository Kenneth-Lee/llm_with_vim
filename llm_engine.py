#!python

"""
本模块提供函数answer()，以供从stdin生成LLM请求，并把输入和输出合并输出到stdout。
直接运行则调用answer()。
模块同时提供一个辅助函数debug()，用来输出answer也会用的调试信息。
"""
import sys
import time
import signal
import json
import os

# 获取脚本所在目录
_script_dir = os.path.dirname(os.path.abspath(__file__))

def debug(msg):
    print("// " + msg)

def _check_environment():
    """检查必须的Python包是否已安装"""
    missing_packages = []
    try:
        import requests
    except ImportError:
        missing_packages.append('requests')

    if missing_packages:
        debug("环境检查失败：缺少必须的Python包")
        debug("缺失的包: " + ", ".join(missing_packages))
        debug("请运行: pip install " + " ".join(missing_packages))
        sys.exit(1)

# 检查环境
_check_environment()

# 现在可以安全导入requests
import requests

# 读入模块配置（llm_engine.json算是代码的一部分，不能没有）
# 从脚本所在目录读取llm_engine.json
_config_path = os.path.join(_script_dir, 'llm_engine.json')
try:
    with open(_config_path, 'r', encoding='utf-8') as file:
        _config = json.load(file)
except FileNotFoundError:
    debug(f"错误: 找不到配置文件 {_config_path}")
    debug("请确保 llm_engine.json 与 llm_engine.py 在同一目录")
    sys.exit(1)
except json.JSONDecodeError as e:
    debug(f"错误: llm_engine.json 格式错误: {e}")
    sys.exit(1)

_ollama_addr_alias = _config["ollama_addr_alias"]
_ollama_model_alias = _config["ollama_model_alias"]
_roles = _config["roles"]

# 一些中间处理函数

def _make_ollama_api(host, api='chat'):
    if host.startswith("http"):
        return host+api
    else:
        return 'http://' + host + ':11434/api/' + api

def _add_msg(req, role, content):
    "给请求增加某个角色的消息"
    if content:
        req['messages'].append({"role":role, "content":content.strip()})

def _output_msg(role, content, end='\n'):
    "输出某个角色的消息"
    if role in _roles.keys():
        role_msg = _roles[role]
    else:
        role_msg = role + ": "
    print(role_msg, content.strip(), sep='', end=end)

def _add_output_msg(req, role, content):
    _add_msg(req, role, content)
    _output_msg(role, content)

# 处理Ctrl-C
def _sig_handler(signal, frame):
    print(r"\generation interrupted")
    sys.exit(0)

signal.signal(signal.SIGINT, _sig_handler)

def _process_inc_directive(line, base_dir=''):
    """
    处理 @inc 指令。
    格式: @inc <filename>
    读取指定文件内容并返回。
    相对路径相对于 base_dir（如果有）或当前工作目录。
    """
    # 解析 @inc 指令，格式: @inc <filename>
    parts = line.strip().split(None, 1)
    if len(parts) < 2:
        debug(f"Invalid @inc directive: {line.strip()}")
        return ""

    filename = parts[1].strip()

    # 验证文件名，防止路径遍历攻击
    # 不允许绝对路径和父目录引用
    if os.path.isabs(filename):
        debug(f"@inc: absolute paths are not allowed: {filename}")
        return ""

    # 检查是否有父目录引用
    if '..' in filename:
        debug(f"@inc: path traversal is not allowed: {filename}")
        return ""

    # 构建完整路径
    if base_dir:
        file_path = os.path.join(base_dir, filename)
    else:
        file_path = filename

    # 规范化路径
    file_path = os.path.normpath(file_path)

    # 防止路径遍历（规范化后不应该有..，但再检查一次）
    if '..' in file_path:
        debug(f"@inc: path traversal is not allowed: {filename}")
        return ""

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # 打印包含提示信息
            print(f"// @inc: included file '{filename}'")
            return content
    except FileNotFoundError:
        debug(f"@inc: file not found: {filename}")
        return ""
    except IOError as e:
        debug(f"@inc: error reading file {filename}: {e}")
        return ""
    except UnicodeDecodeError:
        debug(f"@inc: file encoding error: {filename}")
        return ""

def _parse_input():
    """
    处理stdin的输入信息。返回history,config。
    前者是将要发送的请求，后者是输入中提供的配置

    使用堆栈处理@inc指令：
    - 堆栈每个元素保存 (lines, line_idx, base_dir, depth, is_main_file)
    - 遇到@inc时，压栈当前状态，开始处理被包含的文件
    - 被包含文件的内容需要全部添加到 history
    - 主文件的 @inc 行保留在输出中（不发送给LLM）
    - 最大深度限制为10，防止无限循环
    """
    global _config
    history = _config["request_template"]
    history["messages"] = []
    user_config = None

    # 读取主输入文件
    main_lines = sys.stdin.readlines()

    # 堆栈：每个元素是 (lines, line_idx, base_dir, depth, is_main_file)
    # is_main_file: 标记是否是主文件（用于控制输出）
    # 初始：主文件，从第0行开始，空目录，深度0，是主文件
    stack = [(main_lines, 0, '', 0, True)]
    MAX_DEPTH = 10

    # 当前角色的发言内容
    role = 'none'
    item = ''

    # 收集需要输出的行（只来自主文件，保持@inc指令原样）
    output_lines = []

    # 临时存储被包含文件展开后的内容
    # 格式: {depth: [(role, content), ...]}
    # 当弹栈时，把这些内容添加到 history
    inc_content_cache = {}

    # 追踪上一行是否是角色行（用于处理延续内容不加前缀）
    last_was_role_line = False

    while stack:
        current_lines, line_idx, base_dir, depth, is_main_file = stack[-1]

        # 检查是否当前文件处理完毕
        if line_idx >= len(current_lines):
            # 弹栈前，处理最后的内容
            current_depth = stack[-1][3]
            if item.strip():
                if stack and stack[0][4]:  # 主文件
                    if role == 'config':
                        user_config = item.strip()
                        output_lines.append(_roles['config'] + user_config + '\n')
                        last_was_role_line = True
                    else:
                        if last_was_role_line and history['messages']:
                            # 延续内容，追加到上一条消息
                            last_msg = history['messages'][-1]
                            last_msg['content'] += item
                        else:
                            _add_msg(history, role, item)
                        # 输出
                        if last_was_role_line:
                            output_lines.append(item)
                        else:
                            if role in _roles.keys():
                                role_msg = _roles[role]
                            else:
                                role_msg = role + ": "
                            output_lines.append(role_msg + item)
                        last_was_role_line = True
                else:
                    # 被包含文件
                    if role == 'config':
                        # 配置只添加到缓存，不设置 user_config
                        clean_item = item.strip()
                        if clean_item and current_depth in inc_content_cache:
                            inc_content_cache[current_depth].append(('config', clean_item))
                    elif role != 'none' and current_depth in inc_content_cache:
                        # 只有有效角色才添加到缓存
                        inc_content_cache[current_depth].append((role, item))
                item = ''
                role = 'none'  # 重置角色

            # 弹栈前，把被包含文件的内容添加到 history
            if not is_main_file and current_depth in inc_content_cache:
                for r, c in inc_content_cache[current_depth]:
                    if r == 'config':
                        # 配置只用于设置 user_config，不添加到 LLM 请求
                        if user_config is None:
                            user_config = c
                    else:
                        _add_msg(history, r, c)
                del inc_content_cache[current_depth]

            stack.pop()
            # 如果是主文件处理完毕，结束循环
            if not stack:
                break
            continue

        line = current_lines[line_idx]

        # 更新堆栈当前位置
        stack[-1] = (current_lines, line_idx + 1, base_dir, depth, is_main_file)

        # 处理不同类型的行
        if line.startswith("/"):                # 调试信息，忽略
            continue
        elif line.startswith("#"):
            if is_main_file:
                output_lines.append(line)       # 注释，原封不动保留（仅主文件）
                last_was_role_line = False
        elif line.startswith("@inc "):
            # 处理 @inc 指令
            # 根据设计文档：
            # 1. @inc 指令在输出中保持原样（不展开）- 添加到 output_lines（仅主文件）
            # 2. 展开的内容需要发送给 LLM

            if is_main_file:
                # 输出保持 @inc 指令原样（仅主文件的@inc会被输出）
                output_lines.append(line)
                last_was_role_line = False

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
            if os.path.isabs(filename):
                debug(f"@inc: absolute paths are not allowed: {filename}")
                continue
            if '..' in filename:
                debug(f"@inc: path traversal is not allowed: {filename}")
                continue

            # 构建完整路径
            if base_dir:
                file_path = os.path.join(base_dir, filename)
            else:
                file_path = filename
            file_path = os.path.normpath(file_path)
            if '..' in file_path:
                debug(f"@inc: path traversal is not allowed: {filename}")
                continue

            # 读取被包含的文件
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except FileNotFoundError:
                debug(f"@inc: file not found: {filename}")
                continue
            except IOError as e:
                debug(f"@inc: error reading file {filename}: {e}")
                continue
            except UnicodeDecodeError:
                debug(f"@inc: file encoding error: {filename}")
                continue

            # 获取被包含文件的目录（用于其中的相对路径）
            file_dir = os.path.dirname(filename)
            new_base_dir = file_dir if file_dir else base_dir

            # 将被包含的文件压栈，继续处理其内容（只用于 LLM，不加入 output）
            inc_lines = content.splitlines(keepends=True)
            stack.append((inc_lines, 0, new_base_dir, depth + 1, False))  # False = 不是主文件

            # 初始化被包含文件内容的缓存
            inc_content_cache[depth + 1] = []

        else:                                   # 其他认为是有效输入
            found = False
            for new_role in _roles.keys():       # 一个个匹配是否是新的角色
                if line.startswith(_roles[new_role]):          # 匹配上了
                    # 提交上一个角色的内容（如果有）
                    if role != 'none':
                        if role == 'config':
                            user_config = item.strip()         # 实例配置信息
                            if is_main_file:
                                output_lines.append(_roles[role] + user_config + '\n')
                                last_was_role_line = True
                        else:
                            # 添加到 history 或缓存
                            if is_main_file:
                                if last_was_role_line and history['messages']:
                                    # 延续内容，追加到上一条消息
                                    last_msg = history['messages'][-1]
                                    last_msg['content'] += item
                                else:
                                    _add_msg(history, role, item)
                                # 输出角色和内容
                                if role in _roles.keys():
                                    role_msg = _roles[role]
                                else:
                                    role_msg = role + ": "
                                if last_was_role_line:
                                    output_lines.append(item)
                                else:
                                    output_lines.append(role_msg + item)
                                last_was_role_line = True
                            else:
                                # 被包含文件的内容先缓存，弹栈时再添加到 history
                                if depth in inc_content_cache:
                                    inc_content_cache[depth].append((role, item))
                    elif not is_main_file and item.strip():
                        # 第一个角色且不是主文件，把内容也缓存
                        # (role 是 'none'，但 item 可能有内容)
                        if depth in inc_content_cache:
                            inc_content_cache[depth].append(('none', item))

                    role = new_role                            # 切换到新角色
                    # 兼容Python 3.6+: 手动实现removeprefix
                    prefix = _roles[new_role]
                    item = line[len(prefix):] if line.startswith(prefix) else line
                    found = True
                    break                                     # 找到一个，其他的不用找了

            if not found:                   # 没有找到，整行作为老角色的延续发言
                item = item + line

    # 文件处理完毕，处理最后一个角色的内容（已在上层循环处理过）

    # 输出所有收集的行（保持@inc指令原样）
    sys.stdout.write(''.join(output_lines))

    if user_config:
        try:
            # Use json.loads instead of eval for safety
            # First, try to parse as JSON directly
            import ast
            # Try JSON parsing first (strict)
            try:
                uc = json.loads(user_config)
            except json.JSONDecodeError:
                # If that fails, try ast.literal_eval as a safer alternative to eval
                # This handles Python dict syntax like {'key': 'value'}
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

    # Validate strings for potential command injection
    if isinstance(value, str):
        # Check for potential command injection patterns
        dangerous_patterns = [';', '|', '&', '`', '$(', '${', '\x00']
        for pattern in dangerous_patterns:
            if pattern in value:
                return False
        # Ensure reasonable length limits
        if len(value) > 10000:  # Prevent extremely long values
            return False

    # Validate numeric values
    if isinstance(value, (int, float)):
        # Set reasonable bounds for configuration values
        if name in ['max_tokens', 'temperature', 'keep_alive'] and (value < 0 or value > 100000):
            return False

    return True

def _get_user_config_item(name, default, user_config):
    # 先从config.json的config中读，如果有用户配置，用用户配置覆盖，
    # 如果都没有配置，就给初值。
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
    global _config

    # 时间统计
    start_time = time.time()

    # 先处理输入，其中可能包含配置
    history, user_config = _parse_input()

    # api请求头部
    headers = { 'Content-Type':'application/json'}

    # 组合配置
    common_config = _config['default_config']
    engine_type = _get_user_config_item("engine_type", "ollama", user_config)
    server_addr = _get_user_config_item("server_addr", "localhost", user_config)
    for key in common_config.keys():
        common_config[key] = _get_user_config_item(key, common_config[key], user_config)
    if engine_type == "ollama":
        keep_alive = _get_user_config_item("keep_alive", 60, user_config)

    # 根据引擎类型设置默认参数，调整别名
    if engine_type=='haijing':
        if common_config['model']=='' or common_config['model']=='default':
            common_config['model'] = 'DeepSeek-R1'
        api = 'https://api.atalk-ai.com/chat/completions'
    elif engine_type=='deepseek':
        if common_config['model']=='' or common_config['model']=='default':
            common_config['model'] = 'deepseek-chat'
        api = 'https://api.deepseek.com/chat/completions'
    elif engine_type=='zhipu':
        if common_config['model']=='' or common_config['model']=='default':
            common_config['model'] = 'glm-4.7'
        api = 'https://open.bigmodel.cn/api/coding/paas/v4/chat/completions'
    elif engine_type=='ali':
        if common_config['model']=='' or common_config['model']=='default':
            common_config['model'] ='deepseek-r1'
        api = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
    elif engine_type=='llama':
        api = 'http://' + server_addr + '/v1/chat/completions'
    elif engine_type=='ollama' or engine_type=='default':
        engine_type='ollama'
        if common_config['model']=='' or common_config['model']=='default':
            common_config['model'] ='qwen2.5:0.5b'
        server_addr = _ollama_addr_alias.get(server_addr, server_addr)
        common_config['model'] = _ollama_model_alias.get(
                common_config['model'], common_config['model'])
        api = _make_ollama_api(server_addr)
    else:
        print(f'未知引擎{engine_type}')
        sys.exit(0)

    # 没有给用户配置的生成一个
    if not user_config:
        user_config = common_config.copy()    # 以common配置为基础（不能直接用，两者不重合）
        user_config["engine_type"] = engine_type
        user_config["server_addr"] = server_addr
        if engine_type == 'ollama':
            user_config["keep_alive"] = keep_alive
        print(_roles['config'], user_config)

    # api key需要特殊处理一下，用户配置没有的话，看看有没有全局配置
    if not (engine_type in ['ollama', 'llama']):
        auth = user_config.get('auth', None)
        if not auth:
            auth_keys = _config.get("auth_keys", {})
            auth = auth_keys[engine_type]
        headers['Authorization'] = auth
        # debug(f"change head with {auth}")

    # 根据配置完善请求记录
    for key in common_config.keys():
        history[key] = common_config[key]
    if engine_type == 'ollama':
        history["keep_alive"] = keep_alive
    if engine_type != 'llama':                   # llama不使用stream模式
        history["stream"] = True

    debug(f"api={api}, history={history}, headers={headers}")
    debug("===========>\n")

    # 发起请求
    resp = None
    try:
        # Add timeout for API requests to prevent hanging
        resp = requests.post(api, json=history, headers=headers, stream=True, timeout=(10, 30))
        resp.raise_for_status()
        _output_msg('assistant', '', end='')

        # Validate the response before processing
        if not hasattr(resp, 'iter_lines'):
            debug("Invalid response object received from API")
            return

        if engine_type=='haijing':
            for i in resp.iter_lines():
                if i:
                    try:
                        decoded_line = i.decode('utf-8')
                        print(decoded_line)
                    except UnicodeDecodeError:
                        debug("Skipping invalid UTF-8 sequence in response")
                        continue
        elif engine_type=='zhipu':
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
                                    # Validate response structure
                                    if 'choices' in resp_i and len(resp_i['choices']) > 0:
                                        delta_content = resp_i['choices'][0].get('delta', {}).get('content', '')
                                        if delta_content:
                                            print(delta_content, end='', flush=True)
                                except json.JSONDecodeError:
                                    debug(f"Invalid JSON in response: {resp_s}")
                        else:
                            # Skip non-data lines (like event: lines)
                            pass
                    except UnicodeDecodeError:
                        debug("Skipping invalid UTF-8 sequence in response")
                        continue
        elif engine_type=='ali':
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
                                    # Validate response structure
                                    if 'choices' in resp_i and len(resp_i['choices']) > 0:
                                        delta_content = resp_i['choices'][0].get('delta', {}).get('content', '')
                                        if delta_content:
                                            print(delta_content, end='', flush=True)
                                except json.JSONDecodeError:
                                    debug(f"Invalid JSON in response: {resp_s}")
                        else:
                            debug(f"unknown response: {decoded_line}")
                    except UnicodeDecodeError:
                        debug("Skipping invalid UTF-8 sequence in response")
                        continue
        elif engine_type == 'ollama':
            for i in resp.iter_lines():
                if i:
                    try:
                        resp_i = json.loads(i.decode('utf-8'))
                        # Validate response structure
                        if 'message' in resp_i:
                            content = resp_i['message'].get('content', '')
                            if content:
                                print(content, end='', flush=True)
                    except (json.JSONDecodeError, UnicodeDecodeError) as e:
                        debug(f"Error processing Ollama response: {e}")
                        continue
        elif engine_type == 'llama':
            for i in resp.iter_lines():
                if i:
                    try:
                        resp_i = json.loads(i.decode('utf-8'))
                        # Validate response structure
                        if 'choices' in resp_i and len(resp_i['choices']) > 0:
                            content = resp_i['choices'][0]['message'].get('content', '')
                            if content:
                                print(content, end='', flush=True)
                    except (json.JSONDecodeError, UnicodeDecodeError) as e:
                        debug(f"Error processing Llama response: {e}")
                        continue
        print()
    except requests.exceptions.Timeout:
        print()
        debug("API request timed out. Please check your connection and try again.")
    except requests.exceptions.ConnectionError:
        print()
        debug("Connection error occurred. Please check if the API server is running and accessible.")
    except requests.exceptions.HTTPError as e:
        print()
        debug(f"HTTP error occurred: {e}. Status code: {resp.status_code if resp else 'Unknown'}")
    except Exception as e:
        print()                             # 加一个换行，免得前面输出了一半就异常了
        debug(f"Unexpected error occurred: {e}. Response: {resp}");

    print(f"//updated at {time.asctime()} in {(time.time()-start_time):.1f} seconds", end='')

if __name__ == "__main__":
    answer()
