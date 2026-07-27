# 上下文稳定提交与缓存命中优化设计文档

## 1. 设计目的

- 设计类型：在现有 llm_with_vim 项目上新增一致性保障能力（非重构、非替换）。
- 目标：当用户未编辑上下文时，客户端提交到 LLM 服务端的请求体尽量保持字节级一致，以提高服务端 KV Cache 或请求缓存命中率。
- 设计基线：基于 2026-07-26 的仓库状态。

当前问题：
- 上下文在进入消息结构时存在自动裁剪（如 `strip`），会改变首尾空白。
- 请求通过对象序列化发送，缺少统一的稳定序列化策略，存在键顺序与空白策略不一致风险。
- 缺少一致性可观测性，无法快速证明“未编辑但请求变化”的根因。
- 工具调用结果此前主要以摘要方式回写，未形成可编辑且可稳定重放的标准编码。

## 2. 设计逻辑

### 2.1 核心概念

- 上下文快照（Context Snapshot）：用户提交区间经过解析后的 `messages` 结构快照。
- 规范化器（Canonicalizer）：将待发送结构转为稳定 JSON 文本的函数，保证同输入同输出。
- 请求指纹（Payload Fingerprint）：对最终请求体 UTF-8 字节串做 SHA-256，作为稳定性校验指标。
- 工具角色编码（Tool Role Encoding）：工具调用与工具结果编码为 `Tool:` 角色内容，写入可编辑上下文并参与后续提交。
- 可编辑上下文（Editable Context）：用户在 `.llm` 文件中直接看到和修改的文本，是本项目的唯一交互载体。
- 稳定前缀（Stable Prefix）：未编辑时应保持字节级一致的上下文前段，用于最大化缓存命中。
- 生成后缀（Generated Tail）：工具执行或模型输出后追加的部分，允许生成，但必须遵循稳定落盘规则。

### 2.2 关键设计选择

1. 保留用户内容边界
- 不再对消息 `content` 做 `strip`，避免自动删除首尾空白和换行。
- 仅在确有语义需要时做最小变换（例如换行风格归一化）。

2. 固定请求体序列化
- 使用统一 JSON 序列化参数：`sort_keys=True`、`separators=(",", ":")`、`ensure_ascii=False`、`allow_nan=False`。
- 请求通过稳定 JSON 字节串发送，避免不同运行路径导致的 payload 漂移。

3. 增加可观测性
- 输出 `context_hash` 和 `payload_hash`（仅详细调试模式），用于验证未编辑时一致性。
- 哈希不参与功能逻辑，不影响主流程。

4. 降低隐式状态污染
- 解析输入时对请求模板做深拷贝，避免全局模板在多轮流程中被意外修改。

5. 将工具结果纳入可编辑 Tool 角色
- 工具结果必须以 `Tool:` 角色落盘，而不是摘要注释。
- `Tool:` 采用稳定 JSON 单行编码，至少包含 `v`、`name`、`arguments`、`result`，可选 `id`。
- 用户可以编辑或删除 `Tool:`；未编辑时保持不变可命中缓存，编辑后视为显式上下文变化。

6. 编辑能力与缓存命中分层
- 用户对上下文的编辑只影响编辑点及其之后的消息。
- 编辑点之前的稳定前缀必须保持原样，以便缓存前缀继续命中。
- 对 `Tool:` 行不做二次摘要或重排，避免“未编辑但重编码变化”。

### 2.3 非目标

- 不保证“用户改了但仍命中缓存”。
- 不在本阶段引入跨进程 payload 重放缓存。
- 不改变既有工具调用协议与多模态协议。

## 3. 核心数据结构

### 3.1 Context Snapshot

```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ]
}
```

### 3.2 Tool Role Entry

```json
{
  "v": 1,
  "name": "read_file",
  "arguments": {"path": "a.txt"},
  "result": "...完整结果...",
  "id": "call_123"
}
```

### 3.3 Payload Fingerprint 元信息

```text
context_hash: sha256(stable_json(messages))
payload_hash: sha256(stable_json(full_request_payload))
```

## 4. 接口定义

### 4.1 内部接口

- `_normalize_content_text(text)`
  - 功能：做最小文本归一化（本阶段仅统一换行到 LF）。
- `_stable_json_dumps(obj)`
  - 功能：返回稳定 JSON 文本。
- `_sha256_text(text)`
  - 功能：返回 UTF-8 字节的 SHA-256 摘要。
- `_post_stream_request(api, payload_obj, headers, timeout, trace_label='')`
  - 功能：使用稳定 JSON 序列化后发起流式请求，并返回响应与 payload_hash。
- `_format_tool_role_content(func_name, func_args, result_text, tool_call_id='')`
  - 功能：生成 `Tool:` 角色稳定 JSON 文本。
- `_decode_tool_role_content(content)`
  - 功能：解析 `Tool:` 角色文本，还原为发送给模型的 `role=tool` 内容。

### 4.2 流程关系

- 解析得到 `history.messages`。
- 计算 `context_hash`（调试可见）。
- 填充请求字段后计算 `payload_hash`（调试可见）。
- 发送稳定序列化后的 payload。
- 工具调用发生时，立即输出 `Tool:` 行并写入上下文；下次提交时将 `Tool:` 解析为 `role=tool` 消息。

## 5. 一致性校验

### 5.1 规则

- 同一上下文、同一配置、同一引擎路径下：`payload_hash` 必须一致。
- 若上下文任意字符变化（含空格/换行）：`payload_hash` 可以变化，这是预期行为。
- 若 `Tool:` 行未变化，tool 相关消息序列必须可重放为相同结果。
- 若用户只编辑稳定前缀之后的部分，稳定前缀的 payload 必须保持不变。

### 5.2 测试策略

- 单测 1：消息内容保留首尾空白，不被 `strip`。
- 单测 2：同一对象多次稳定序列化结果一致。
- 单测 3：同输入重复计算 `payload_hash` 一致。
- 单测 4：同一 `Tool:` 行重放后得到相同的 `role=tool` 消息序列。
- 单测 5：编辑点之前的消息指纹不变，编辑点之后允许变化。

## 6. 落地计划

1. 第 1 阶段（本次）
- 引擎内落地稳定序列化、哈希可观测、内容保真。

2. 第 2 阶段
- 增加可选“请求重放缓存”（跨进程），以文档路径+光标范围+配置指纹+`Tool:` 行指纹作为键。

3. 第 3 阶段
- 在 Vim/VSCode 端增加“未编辑提交提示”与一致性诊断展示。
- 为 `Tool:` 角色提供折叠/高亮和快速清理能力。

## 7. 变更历史

| 日期 | 变更内容 | 原因 |
|---|---|---|
| 2026-07-26 | 初版文档创建 | 支撑上下文稳定提交与缓存命中优化 |
| 2026-07-26 | 切换为 Tool 角色编码主方案 | 贴合可编辑上下文目标，替代摘要输出 |
