# ContextForge Provider 新增与接入指南

## 1. 指南目标

本指南用于规范如何新增一个 Provider，同时满足两个硬约束：

1. 对最终用户配置尽量简单、可省略、可诊断。
2. 保持现有会话接口兼容：继续使用 `Configure:` 角色，不强制修改旧写法。

## 2. 用户无感原则

新增 Provider 时，优先考虑用户最少输入：

1. 零配置可运行
- 必须提供可工作的 `defaults.model` 与 `endpoint.default_host/default_port`。

2. 最小配置可运行
- 用户只写 `Configure: {'engine_type': 'new_provider'}` 也应该可发请求。

3. 常见配置短路径
- 仅在需要时才要求 `model`、`server_addr`、`auth`。

4. 错误可理解
- 校验错误必须给“原因 + 建议 + 示例”，不能只报技术异常。

## 3. 向后兼容原则（Configure 不变）

1. 保留字段习惯
- `engine_type`：仍作为 Provider 选择键。
- `server_addr`：仍作为会话层目标地址覆盖键。
- `model`、`temperature`、`max_tokens`：语义保持一致。

2. 新字段只增不破
- 新能力字段必须是可选字段。
- 旧会话文件不应因缺少新字段而报错。

3. 兼容解析
- `Configure:` 继续支持 JSON 和 Python dict 风格。
- 对旧别名与旧值提供迁移提示，不强制立即改写。

## 4. 新增 Provider Checklist

### 4.1 定义阶段

1. 新建 Provider Spec
- 路径：`~/.config/contextforge/providers/<provider_id>.json`（用户层）或内置目录（应用层）。

2. 填写最小必需字段
- `id`
- `protocol`
- `endpoint.template`
- `endpoint.default_host`
- `endpoint.default_port`
- `auth.type`
- `defaults.model`
- `response_mapping.mode`

3. 定义覆盖策略
- `overrides.allowed_in_session`
- `overrides.readonly`

### 4.2 校验阶段

1. Schema 校验通过
- 字段完整性、类型、枚举值。

2. 合并校验通过
- 在 L0-L5 合并后仍满足约束。

3. 兼容校验通过
- 旧 `Configure:` 写法可正常运行。

### 4.3 运行验证阶段

1. 零配置 smoke test
- 不写 `Configure:` 或仅写 `engine_type` 可通。

2. 会话覆盖 test
- 覆盖 `model/server_addr/temperature` 生效。

3. 错误诊断 test
- 错误 host、错误 auth、错误字段均有可读提示。

4. 工具调用 test
- 若 `features.tools=true`，验证 tool call 循环。

## 5. 字段映射建议

### 5.1 推荐保留的用户层键名

建议继续沿用以下键名，减少用户迁移成本：

- `engine_type`
- `server_addr`
- `model`
- `temperature`
- `max_tokens`
- `connect_timeout`
- `read_timeout`
- `tools`
- `thinking`

### 5.2 Provider 私有参数

Provider 私有参数（如某些平台的特定开关）应遵循：

1. 非必需参数有默认值。
2. 参数名自解释，并在报错中给示例。
3. 若参数只影响协议解析，优先放入 spec 只读区，而非会话层。

## 6. 错误提示规范

新增 Provider 时，错误提示建议遵循以下模板：

1. 语法类
- `@// ERROR: Configure 格式错误：<原因>`
- `@// HINT: 示例 Configure: {'engine_type': 'xxx', 'model': '...'}'

2. 字段类
- `@// ERROR: 字段 '<field>' 类型错误，期望 <type>，实际 <type>`
- `@// HINT: 可选值：<a|b|c>`

3. 覆盖冲突类
- `@// ERROR: 会话层不允许覆盖 '<field>'`
- `@// HINT: 请在用户配置或 provider spec 中设置该字段`

## 7. 版本与迁移

1. `schema_version` 必填，破坏性变化必须升级。
2. `spec_version` 用于 provider 自身演进。
3. 字段弃用采用两阶段：
- 阶段 1：兼容读取 + 警告
- 阶段 2：文档公告后移除

## 8. 验收标准

新增一个 Provider 被视为完成，至少满足：

1. 用户最少配置可运行。
2. 旧 `Configure:` 格式无需改写。
3. 关键错误可读且带建议。
4. 回归测试通过（请求、流式、工具、失败路径）。

## 9. 变更历史

| 日期 | 变更内容 | 原因 |
|---|---|---|
| 2026-07-28 | 初版 Provider 接入指南 | 固化新增 Provider 流程与用户兼容约束 |
