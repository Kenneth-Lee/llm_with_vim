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

def _parse_input():
    """
    处理stdin的输入信息。返回history,config。
    前者是将要发送的请求，后者是输入中提供的配置
    """
    global _config
    history = _config["request_template"]
    history["messages"] = []
    user_config = None

    # 对输入分段
    lines=sys.stdin.readlines()

    # 处理输入的内容
    role='none'
    item=''
    for line in lines:
        if line.startswith("/"):                # 调试信息，忽略
            continue
        elif line.startswith("#"):
            print(line)                         # 注释，原封不动保留
        else:                                   # 其他认为是有效输入
            found = False
            for new_role in _roles.keys():       # 一个个匹配是否是新的角色
                if line.startswith(_roles[new_role]):          # 匹配上了
                    if role!='none':
                        if role == 'config':
                            user_config = item.strip()         # 实例配置信息
                            print(_roles[role], user_config)
                        else:
                            _add_output_msg(history, role, item)   # 提交老消息
                    role = new_role                            # 切换到新角色
                    # 兼容Python 3.6+: 手动实现removeprefix
                    prefix = _roles[new_role]
                    item = line[len(prefix):] if line.startswith(prefix) else line
                    found = True
                    break                                     # 找到一个，其他的不用找了

            if not found:                   # 没有找到，整行作为老角色的延续发言
                item = item + line

    if item.strip():
        _add_output_msg(history, role, item) # 全部结束，如果最后一个角色有发言，补上他的发言

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

    # debug(f"api={api}, history={history}, headers={headers}")
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
