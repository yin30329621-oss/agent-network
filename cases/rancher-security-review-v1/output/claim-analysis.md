# Rancher Security Review v1 Claim Analysis

## 1. 总体统计

本次离线抽取结果来自 `claims.json`：

| 指标 | 数量 |
| --- | ---: |
| candidate_count | 260 |
| extracted_count | 149 |
| duplicate_count | 0 |
| failure_count | 0 |
| selected_count | 149 |
| truncated_count | 0 |

## 2. Claim type 分布

| claim_type | 数量 |
| --- | ---: |
| security_control | 43 |
| architecture | 39 |
| behavior | 30 |
| authorization | 17 |
| version_support | 14 |
| other | 5 |
| configuration | 1 |
| 合计 | 149 |

## 3. 主题命中

以下数量按 Claim 文本中的关键词命中统计，彼此不互斥：

| 主题 | Claim 数量 |
| --- | ---: |
| Cluster Agent | 42 |
| Reverse Tunnel | 14 |
| RBAC | 11 |
| Token | 26 |
| Cloud Credential | 12 |
| CVE | 5 |
| RKE2 | 6 |

关键词命中不等于主题 Claim 已经适合验证；例如 Token 可能只是表格字段或背景说明，仍需结合上下文和 evidence 要求筛选。

## 4. 质量问题

### 过于宽泛或不可独立验证

部分 Claim 是长段落，混合多个事实、结论和建议。例如对 Rancher 定位、整体安全风险或产品能力的概括，单条 Claim 包含多个独立命题，引用难以精确对齐。建议拆分为单一主体、单一关系、单一断言。

### 非事实描述

发现以下类型不应直接进入 Fact Review：

- 章节标题和小节标题，例如 `3.2 管理平面`、`4.4 Token 与 Credential 安全管理`。
- 表格列头或组件清单，例如 `类型 | 主要用途 | 生命周期 / 使用阶段`。
- 观察指引、判断建议和风险结论，例如“应结合实际部署方式判断”或“可作为初步感知依据”。
- 报告结构性说明，例如“本章重点……”和“因此……”等论证性文本。

这些内容虽被抽取为 Claim，但不一定具有可独立验证的事实语义。

### 重复含义

`duplicate_count=0` 仅表示抽取器未发现规范化文本完全重复。语义上仍存在候选重复或高度相关的 Claim，例如：

- Rancher 总体定位与后续“主要功能”总述；
- Cluster Agent 的部署、建立通信、任务执行和状态同步分别描述同一链路的不同片段；
- Token / Credential 概览、存储方式和调用流程之间存在上下文重叠；
- RKE2 安全定位与后续 FIPS、CIS、加固能力描述需要按事实粒度去重。

当前没有把这些语义相关项自动合并，以避免破坏稳定 `claim_id`；应在进入 reviewer 前通过人工或显式规则建立 canonical claim 集合。

### 不适合直接进入 Fact Review 的 Claim

优先排除：`claim_type=other` 的 5 条、明显标题/表头、纯组件名称、只有“通常/可通过/注意事项”的说明句，以及包含多个结论的长段落。CVE 相关 Claim 可以保留，但必须拆成 CVE、受影响版本、影响组件和修复建议等可分别核验的 Claim。

此外，当前终端输出中的中文出现疑似 UTF-8 解码异常（乱码）。在进入后续验证前应确认 `input.md` 和 `claims.json` 的编码字节一致；若文件本身正常，则仅是终端显示问题。

## 5. Dual Fact 建议集

不建议将 149 条全部送入 Dual Fact。第一轮建议保留约 **60–80 条**高价值、原子化 Claim，优先顺序为：

1. CVE、Token、Cloud Credential、RBAC、Reverse Tunnel 和 Cluster Agent 的安全控制与通信事实；
2. RKE2 的版本、FIPS/CIS 和安全配置事实；
3. 能明确绑定官方文档或已有 evidence chunk 的架构事实。

剔除或延后标题、表格元数据、泛化产品介绍、推测性结论和无法独立引用的复合 Claim。最终数量应由人工筛选结果和 evidence 可用性决定，而不是由关键词命中数直接决定。

## 6. 结论

本次 extraction 在结构层面成功，但“抽取成功”不代表“适合事实核验”。建议先建立本案例的 canonical Claim 子集和排除原因，再运行 Evidence Pipeline 与 Dual Fact；不要修改 Claim schema，也不要把质量筛选隐式塞入现有 reviewer 流程。
