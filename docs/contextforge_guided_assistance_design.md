# ContextForge 自解释与新手引导设计文档

## 1. 设计目的

本设计用于降低 ContextForge 的上手门槛，让用户尽量不需要反复查手册：

1. 出错时自动给出可执行的修复建议。
2. 用户请求帮助时，直接在会话内输出当前可配置项与示例。
3. 模型不可用时，自动探测服务器支持模型并给出候选（若服务端支持）。

本设计坚持两个既有约束：

1. 保持现有会话接口不变，继续使用 Configure: 角色。
2. 不强制用户填写复杂配置，默认零配置可运行。

## 2. 设计原则

1. 就地反馈
- 所有提示优先以注释行输出到当前会话附近，避免跳出编辑流。

2. 可执行建议
- 提示必须包含可直接复制的配置片段或下一步动作，不仅是错误描述。

3. 分级提示
- 信息级（Info）: 常规引导
- 警告级（Warn）: 配置可运行但有潜在问题
- 错误级（Error）: 请求失败或配置无效

4. 保守兼容
- 默认只加提示不改变业务行为。
- 必要时新增可选开关，不破坏旧会话。

## 3. 用户可见交互规范

### 3.1 注释提示格式

统一使用会话注释行输出：

- @// INFO: ...
- @// WARN: ...
- @// ERROR: ...
- @// HINT: ...

示例：

@// WARN: unknown tools ignored: ok
@// HINT: valid tools: read, write, edit, bash, search, list_dir, python, web_fetch, view_image

### 3.2 帮助请求触发

保持现有接口，不新增命令通道。支持以下触发方式（任一）：

1. 用户问题触发
- User: help
- User: 如何配置当前provider
- User: show config options

2. 配置意图触发
- User: model有哪些
- User: 服务器支持哪些模型

触发后，系统在 Assistant 区块前后输出引导注释，不中断正常流程。

## 4. 提示能力设计视图

### 4.1 能力 A：未知工具告警（默认开启）

目标：避免工具名拼写错误被静默忽略。

行为：

1. Configure.tools 中出现未知工具名时：
- 继续运行（兼容当前行为）
- 输出警告与有效工具列表

2. 输出示例：
- @// WARN: unknown tools ignored: ok
- @// HINT: valid tools: read, write, edit, bash, search, list_dir, python, web_fetch, view_image

备注：
- 不引入严格模式作为默认行为。
- 先做告警，后续可选扩展 strict_tools。

### 4.2 能力 B：配置诊断助手（Config Doctor）

目标：当配置错误时给出最小修复路径。

覆盖场景：

1. Configure 语法错误
- 提示合法格式样例（JSON 和 Python dict 风格）

2. 字段错误
- 未知字段
- 类型错误
- 超出范围

3. 覆盖冲突
- 会话覆盖只读字段时，告知应在哪一层配置

输出模板：

- @// ERROR: invalid Configure field: xxx
- @// HINT: allowed fields for session: model, temperature, max_tokens, tools, thinking, server_addr

### 4.3 能力 C：模型缺失自愈提示（Model Discovery）

目标：model 找不到时自动引导用户选对模型。

触发条件：

1. 请求返回模型不存在类错误（HTTP 4xx + 关键字匹配）
2. 用户显式请求“列出模型”

处理流程：

1. 判断当前 provider 是否声明 model_query_url
2. 若支持，自动请求模型列表接口
3. 输出可选模型前 N 个（如 20 个）
4. 给出可直接替换的 Configure 建议

输出示例：

@// ERROR: model not found: glm-5.2:cloud
@// INFO: server supports 12 models
@// HINT: try one of: qwen2.5:0.5b, deepseek-r1:8b, llama3.2:1b
@// HINT: Configure: {'engine_type': 'ollama', 'model': 'qwen2.5:0.5b'}

降级策略：
- 若 provider 不支持模型查询，提示“当前平台未提供模型列表接口”。

### 4.4 能力 D：首次使用引导（可选）

目标：新用户首次成功运行后知道下一步可做什么。

触发：
- 检测用户配置目录缺失或首次生成

输出：
- 常见配置入口路径
- 最小 Configure 示例
- 如何查看模型和工具说明

## 5. Provider 侧契约扩展

在 Provider Spec 中补充可选字段，供引导系统使用：

1. help.provider_intro
- 一句话介绍 provider 与典型用法

2. help.common_examples
- 若干可复制 Configure 示例

3. diagnostics.model_not_found_patterns
- 用于识别“模型不存在”错误的关键字或正则模式

4. diagnostics.auth_error_patterns
- 认证失败错误识别模式

5. diagnostics.network_error_patterns
- 网络/域名/连接失败识别模式

6. model_query.url_template
- 服务器模型列表接口（已在当前 spec 初步引入）

## 6. 配置项设计

新增全局配置（用户层，可省略）：

1. guided_assistance.enabled
- 默认 true

2. guided_assistance.level
- basic | verbose
- 默认 basic（只输出关键提示）

3. guided_assistance.max_model_suggestions
- 默认 20

4. guided_assistance.show_first_run_tips
- 默认 true

说明：
- 会话层 Configure 不需要新增这些字段。
- 保持 Configure 语义稳定。

## 7. 实施分阶段

### Phase 1（低风险，优先）

1. 未知工具告警
2. 配置字段错误提示
3. 模型不存在时自动尝试模型查询并提示

### Phase 2

1. 帮助请求触发器
2. provider intro 与示例输出

### Phase 3

1. 首次使用引导
2. 更细粒度诊断模式（auth/network/model）

## 8. 验收标准

1. 配置写错时，用户能在当前会话看到明确修复建议。
2. 工具名写错时不再静默。
3. 模型不存在时（且服务端支持），能看到可选模型列表。
4. 不修改现有 Configure 接口，不破坏已有会话文件。
5. 默认行为保持兼容，仅新增提示能力。

## 9. 与当前重构的关系

本设计与 Provider 抽象重构天然互补：

1. Provider Spec 提供诊断元信息。
2. Runtime 消费元信息做统一提示。
3. 用户不需要知道平台细节，也能完成自助排障。

## 10. 变更历史

| 日期 | 变更内容 | 原因 |
|---|---|---|
| 2026-07-28 | 初版自解释引导设计 | 降低学习门槛，减少手册依赖 |
