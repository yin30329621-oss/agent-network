# Agent Network v0.3: Evidence Verification / RAG MVP

## 1. 项目目标

v0.3 将 Agent Network 从“提出审稿疑点”升级为“基于官方证据核验技术声明”。核心原则是：

- LLM 提取声明、归纳证据和解释冲突，但不是事实来源。
- 官方文档、公告、Release Notes 和权威漏洞数据是事实依据。
- 本地规则负责版本、标识符、域名、组件和证据一致性的确定性比较。
- 没有证据时输出 `not_verified` 或 `insufficient_evidence`，不得推断为错误。
- 每项核验结论必须能追溯到 URL、文档版本、检索时间、证据片段和哈希。
- v0.3 不新增 Agent；Claim Extraction 和 Evidence Verification 是现有 Fact Agent 的不同调用阶段。

首期聚焦 Rancher、SUSE、Fleet、Kubernetes、RKE/RKE2、EKS，以及相关 CVE、版本、安全公告和架构行为。系统不尝试验证报告中的每个自然语言句子，只处理可外部验证且对结论有实际影响的声明。

## 2. 当前问题

v0.2 已具备四 Agent、结构化 Finding、运行审计和严格调用计数，但仍有以下边界：

1. Fact 主要依赖模型已有知识，不能可靠核验新 CVE、版本和公告。
2. Security 在特定 SiliconFlow/Qwen 组合下可能把输出预算消耗在 `reasoning_content`。
3. Logic 适合检查论证，不能承担外部事实裁决。
4. Merge 能合并 Finding，但尚未判断证据质量、版本适用性和引用是否真正支持声明。
5. 长报告受 Provider 超时、网络波动和上下文预算影响。
6. 当前结果表示“疑点”，不能证明技术陈述正确。

## 3. 范围与非目标

### 3.1 首期范围

- Rancher Server、Cluster Agent、Fleet Agent、Bundle 的职责与通信关系。
- WebSocket、Reverse Tunnel、HTTPS、TLS/mTLS 的公开行为。
- ServiceAccount Token、Registration Token、API Token、Cloud Credential、Secret。
- Rancher RBAC、Kubernetes RBAC、Impersonation 相关机制。
- Local Cluster、Downstream Cluster，以及常见 Kubernetes 工作负载对象。
- Rancher、RKE、RKE2、EKS 的产品和组件关系。
- CVE 存在性、CVSS、影响版本、修复版本、安全公告和 Release Notes。

### 3.2 非目标

- 不验证纯作者观点、未公开实现细节或无法从公开资料证明的内部环境事实。
- 不把搜索摘要、第三方博客或 LLM 记忆作为最终证据。
- 不新增第五个 Agent。
- 不在 v0.3 Phase 1 实现 Chunk Review、联网抓取、向量数据库或真实 API 调用。
- 不默认对每条 Claim 单独调用模型。

## 4. 目标架构

```text
Markdown Report
      |
      v
Input Preflight / Section Splitter
      |
      v
Claim Extraction (Fact Agent stage or local budget extractor)
      |
      v
Claim Normalizer / Classifier / Deduplicator
      |
      v
Evidence Orchestrator
  |          |             |
  |          |             +--> Online Official API Adapters
  |          +----------------> Local Official Document Index
  +---------------------------> Evidence Cache / Snapshot Store
      |
      v
Deterministic Matcher
(domain, product, component, version, identifier)
      |
      v
Evidence Packages
  |              |               |
  v              v               v
Fact Evidence   Security Review  Logic Review
Analyst         with Evidence    without fact adjudication
  \              |              /
           Merge / Evidence Judge
                    |
                    v
       Markdown + JSON + Run Registry
```

### 4.1 新增的非 Agent 模块

| 模块 | 职责 |
| --- | --- |
| `sectioning` | 保留标题和行号地切分 Markdown |
| `claims` | Claim schema、规范化、分类和去重 |
| `evidence.sources` | 官方来源适配器与白名单策略 |
| `evidence.retrieval` | 查询构造、检索和页面获取编排 |
| `evidence.cleaning` | 主体提取、文本清洗和分段 |
| `evidence.matching` | BM25/向量候选融合及确定性过滤 |
| `evidence.store` | 缓存、快照、哈希和索引清单 |
| `verification` | 状态规则、版本比较和 Evidence Package |

这些模块不拥有模型人格，不计为 Agent。所有外部访问必须通过 Evidence Source Adapter，LLM Provider 不得直接承担网页检索职责。

## 5. Claim Schema

建议使用稳定英文键和字符串枚举：

```yaml
claim_id: claim-...
source_file: reports/example.md
section: "通信机制"
line_start: 120
line_end: 124
original_text: "..."
normalized_claim: "Cluster Agent initiates ..."
claim_type: communication_flow
entities:
  - type: component
    value: Cluster Agent
product: rancher_manager
component: cluster_agent
version_scope:
  raw: "Rancher 2.8-2.10"
  constraints:
    - ">=2.8.0"
    - "<2.11.0"
  channel: stable
verification_priority: high
requires_external_evidence: true
status: pending
```

### 5.1 字段约束

| 字段 | 约束 |
| --- | --- |
| `claim_id` | 单次运行内稳定唯一；建议由来源位置和规范化文本生成哈希 |
| `source_file` | 相对路径或逻辑名称，不复制私有报告内容到缓存元数据 |
| `section` | 最近的 Markdown 标题路径 |
| `line_start/line_end` | 一基行号，必须覆盖 `original_text` |
| `original_text` | 最小完整声明，不扩展上下文，不改写原文 |
| `normalized_claim` | 单一、可检索、可判断的陈述句 |
| `entities` | 类型化实体；不得只保留无类型字符串 |
| `product/component` | 使用受控词表，避免 Rancher Manager、Fleet、RKE2 混淆 |
| `version_scope` | 保留原文并尽可能解析约束；未知时显式为 `unknown` |
| `verification_priority` | `low/medium/high/critical`，表示核验优先级而非安全严重度 |
| `status` | Claim 处理状态，不复用 Finding severity |

### 5.2 Claim Type

- `architecture_behavior`
- `communication_flow`
- `authentication`
- `authorization`
- `credential_storage`
- `token_lifecycle`
- `kubernetes_behavior`
- `rancher_feature`
- `version_claim`
- `cve_existence`
- `cve_affected_version`
- `cve_fixed_version`
- `cvss`
- `security_recommendation`
- `terminology`

辅助分类应区分：`externally_verifiable_fact`、`security_judgment`、`logic_issue`、`author_opinion` 和 `non_public_environment_fact`。后四类不应被强行送入事实检索。

## 6. Evidence Schema

```yaml
evidence_id: evidence-...
claim_id: claim-...
source_type: rancher_documentation
source_title: "Communicating with Downstream User Clusters"
source_url: "https://ranchermanager.docs.rancher.com/..."
official_domain: ranchermanager.docs.rancher.com
retrieved_at: "2026-07-12T08:00:00Z"
published_at: null
updated_at: "2026-06-20T00:00:00Z"
product_version: "2.14"
excerpt: "..."
excerpt_hash: sha256:...
relevance_score: 0.91
source_priority: 100
supports_claim: true
contradicts_claim: false
notes: "Applies to Rancher Manager 2.14 documentation."
```

### 6.1 必要审计字段

- `source_url` 必须是最终规范化 URL，不保存搜索结果页 URL。
- `official_domain` 必须通过白名单校验，不能由模型自行声明。
- `retrieved_at` 使用 UTC；`published_at/updated_at` 不存在时保留 `null`。
- `product_version` 来自页面路径、结构化元数据或适配器规则，不由 LLM 猜测。
- `excerpt` 仅保存支持判断所需的最小片段，并保留相邻标题。
- `excerpt_hash` 对规范化后的片段计算 SHA-256。
- `supports_claim` 与 `contradicts_claim` 可同时为 `false`；不得仅凭高相关度设为支持。
- 同一 Evidence 可以与多个 Claim 关联，但每个 Claim-Evidence 匹配应有独立判断记录。

### 6.2 Evidence Package

Evidence Package 是提供给 Fact、Security 和 Merge 的最小上下文：

```yaml
claim: Claim
candidate_evidence: [Evidence]
deterministic_checks:
  domain_allowed: true
  product_match: true
  component_match: true
  version_match: false
  identifier_match: true
retrieval_summary:
  queries: ["..."]
  candidates_considered: 18
  candidates_rejected: 14
  rejection_reasons:
    wrong_version: 6
    wrong_component: 5
    unofficial_domain: 3
```

## 7. Verification Status

| 状态 | 使用条件 |
| --- | --- |
| `verified` | 至少一项高优先级官方证据明确支持，且没有同级或更高优先级冲突 |
| `contradicted` | 适用版本和组件一致的官方证据明确否定 Claim |
| `partially_verified` | Claim 包含多个子结论，仅部分得到支持，或证据只覆盖部分范围 |
| `not_verified` | 已完成检索，但没有证据能支持或否定 |
| `conflicting_sources` | 两个适用且可信的官方来源给出无法消解的不同结论 |
| `version_mismatch` | 找到相关证据，但证据与 Claim 的产品版本范围不一致 |
| `insufficient_evidence` | 页面缺失、证据片段不完整、检索失败或来源质量不足 |
| `not_applicable` | 作者观点、环境私有事实或不需要外部核验的内容 |

确定性状态规则优先于 LLM 文本：

1. 没找到证据不等于错误。
2. 模型不知道不等于错误。
3. 只有适用版本和组件一致的官方证据明确冲突，才能输出 `contradicted`。
4. 版本不一致时先输出 `version_mismatch`，不能用新版行为覆盖旧版报告。
5. 官方来源冲突时保留双方 Evidence，输出 `conflicting_sources` 并要求人工复核。
6. CVE 不存在的判断至少需要 CVE.org/NVD/官方 CNA 或 Rancher/SUSE 公告查询结果；单一接口无结果只能是 `not_verified`。

## 8. 官方来源白名单与优先级

### 8.1 来源等级

| 优先级 | 来源 | 用途 |
| ---: | --- | --- |
| 100 | `documentation.suse.com` | SUSE 产品文档、生命周期和安全信息 |
| 100 | `ranchermanager.docs.rancher.com` | Rancher Manager 版本化官方文档 |
| 100 | `rancher.com/docs` | 兼容旧文档入口；应解析最终官方落点 |
| 100 | Rancher/SUSE 官方 Security Advisory | 影响版本、修复版本和缓解措施 |
| 95 | `fleet.rancher.io` | Fleet、Bundle、GitRepo 和 Agent 行为 |
| 95 | `github.com/rancher/rancher` | 源码、官方 Release、Issue/PR 的补充证据 |
| 95 | `github.com/rancher/security-advisories` | Rancher 官方安全公告仓库（存在时） |
| 90 | `kubernetes.io` | Kubernetes 对象、RBAC、Token、Secret 等上游行为 |
| 85 | `cve.org` | CVE Record 和 CNA 数据 |
| 85 | `nvd.nist.gov` | CVSS、CPE 和漏洞元数据；注意同步延迟 |
| 80 | `github.com/advisories` | GHSA 和关联生态元数据 |
| 80 | `helm.sh` | Helm 行为 |
| 80 | `docs.docker.com` | Docker 行为 |

GitHub 不能只按域名放行。适配器必须同时校验组织、仓库和内容类型；普通用户 Issue、Fork、评论和搜索摘要不得自动成为最终证据。

### 8.2 禁止作为最终证据

- 搜索引擎摘要、AI 摘要和缓存摘要。
- CSDN、博客园、个人博客、论坛和转载文章。
- 未验证归属的 GitHub Fork、Gist、Issue 评论或 Discussion。
- 模型生成的 URL、引用或文档标题。

第三方资料可用于生成检索线索，但不得进入最终 Evidence 列表的“官方证据”分组。

## 9. 推荐的混合 RAG 方案

推荐“本地官方文档库 + 在线官方 API + 全量本地缓存”的混合方案。

### 9.1 方案比较

| 方案 | 优点 | 缺点 | 适用内容 |
| --- | --- | --- | --- |
| 在线检索 | 最新、覆盖新 CVE/公告/Release | 网络不稳定、页面变化、复现困难、限流 | CVE、版本、公告、Release Notes |
| 本地知识库 | 稳定、快速、可复现、可离线测试 | 需要同步、占用存储、可能过期 | 架构、通信、RBAC、Token、Fleet、Kubernetes 行为 |
| 混合方案 | 同时兼顾时效性和复现性 | 实现与运维复杂度较高 | 推荐默认方案 |

### 9.2 推荐理由

- Rancher 架构和 Kubernetes 基础行为变化相对慢，适合版本化本地索引。
- CVE、修复版本和公告高度时效化，必须查询在线官方数据。
- 在线结果立即写入内容寻址缓存，后续运行可固定到同一证据快照。
- 在网络不可用时允许使用缓存，但必须标记缓存年龄和 `stale` 状态。
- 检索模式和 LLM Provider 是两条独立配置轴，便于测试和审计。

## 10. 检索与匹配流程

1. **Markdown 章节切分**：保留标题路径、行号、代码块和表格边界。
2. **Claim Extraction**：批量提取高价值、可单独判断的声明。
3. **Claim 去重**：使用规范化实体、Claim Type、版本范围和文本相似度合并重复声明。
4. **Claim 分类**：区分外部事实、安全判断、逻辑问题、作者观点和私有环境事实。
5. **查询构造**：由模板和受控实体生成，不接受模型生成的任意域名。
6. **官方来源检索**：按 Claim Type 路由到文档索引、CVE API、Release Adapter 等。
7. **证据页面抓取**：遵守超时、限流、重试上限和内容类型白名单。
8. **文本清洗**：去导航、脚本和重复页脚，保留标题、表格、代码及版本提示。
9. **证据分段**：按语义标题切分，保留页面 URL、锚点和字符偏移。
10. **混合检索**：BM25、实体精确匹配和 embedding 候选融合。
11. **版本过滤**：先过滤产品、组件、文档版本和发布日期，再排序相关度。
12. **组件过滤**：使用受控组件图谱消除同名词歧义。
13. **Evidence Package**：每个 Claim 最多携带少量高质量片段，避免上下文膨胀。
14. **确定性比较**：比较 CVE ID、SemVer 范围、产品、组件和方向性术语。
15. **LLM 解释**：Fact 解释证据是否支持，不得覆盖确定性检查。
16. **Merge 裁决**：GLM-5.2 综合证据、Fact、Security、Logic 和冲突规则。
17. **证据报告**：输出覆盖率、状态、证据快照标识和人工复核项。

### 10.1 防止版本与组件混淆

每个文档块都附带以下身份元组：

```text
(product_family, product, component, version, documentation_channel, published_at)
```

- `rancher_manager`、`fleet`、`rke`、`rke2`、`kubernetes`、`eks` 是不同产品域。
- `cluster_agent`、`fleet_agent`、`system_agent`、`registration_token` 等使用稳定组件 ID。
- 页面没有可确定版本时标记 `unknown`，降低优先级，不继承查询中的版本。
- 版本化文档路径优先于 `latest` 文档；报告未给版本时不得假定最新版。
- 跨产品证据只能作为背景，不得直接支持目标组件行为。

### 10.2 官方资料冲突

冲突处理顺序：

1. 判断产品和组件是否相同。
2. 判断版本范围和发布时间是否相同。
3. 优先采用同版本的 Rancher/SUSE 官方文档或安全公告。
4. 将源码/Release Note 作为行为变化的补充证据。
5. 若同级来源仍冲突，输出 `conflicting_sources`，不得自动选择更符合 Claim 的一方。

### 10.3 证据快照

在线获取内容时保存：规范化 URL、最终 URL、HTTP 状态、ETag、Last-Modified、检索时间、内容哈希、清洗器版本、分段器版本、片段哈希和来源适配器版本。建议使用内容寻址目录：

```text
data/evidence/
  manifests/
  snapshots/sha256/<hash>
  excerpts/sha256/<hash>
  indexes/
  cache/
```

Phase 1 只定义接口和 fixture，不创建真实抓取数据。是否提交快照应按来源许可和体积单独决定；测试 fixture 可以提交，在线缓存默认不提交。

## 11. Agent 职责变化

### 11.1 Fact Agent：Evidence Analyst

- 批量提取待核验 Claim，或解释已生成的 Claim。
- 只根据 Evidence Package 判断支持、冲突、部分支持或证据不足。
- 不得根据模型记忆判定 CVE、版本和公告真假。
- 不得创建 Evidence 中不存在的 URL、版本或引用。
- 无证据时必须输出 `not_verified` 或 `insufficient_evidence`。
- Fact 可以在同一运行中承担 Claim Extraction 与 Fact Verification 两个阶段，但仍是同一个 Agent。

### 11.2 Security Agent：Evidence-Aware Security Reviewer

- 只接收与 Token、RBAC、Secret、Credential、TLS、Impersonation、Agent 权限和 CVE 相关的 Evidence Package。
- 判断报告是否遗漏安全前提、威胁边界或错误放大/弱化风险。
- 区分“机制事实”和“安全评价”；机制事实必须引用 Evidence。
- 不自行判断 CVE、CVSS、版本和修复状态。
- 延续紧凑 JSON、Finding 数量上限和不输出 reasoning 的策略。

### 11.3 Logic Agent：Argument Reviewer

- 只检查结构、前提、因果关系、内部一致性和结论强度。
- 可以指出“结论缺少前提”，但不能补写外部事实。
- 不输出新 URL、CVSS、版本或产品默认行为。
- Logic 结果不改变 Verification Status，只作为 Merge 的论证质量输入。

### 11.4 Merge Agent：Evidence Judge / Senior Reviewer / Final Editor

GLM-5.2 的新职责：

1. 综合 Claim、Evidence、确定性检查和三个专业 Agent 的意见。
2. 判断证据是否真正覆盖 Claim 的产品、组件、版本和语义。
3. 保留冲突来源和不同意见，不用模型记忆覆盖证据。
4. 输出 Verification Status、证据等级和人工复核标记。
5. 生成“原文 → 建议改写 → 修改理由”。
6. 输出专家可读的中文最终报告。
7. 不自行联网，不创建 Evidence Store 中不存在的引用。

Merge 的自然语言裁决不能修改本地确定性规则已确认的域名、版本匹配和标识符比较结果。

## 12. Provider 与 Evidence Source 分离

### 12.1 LLM Provider

```yaml
agents:
  fact:
    provider: deepseek_official
  security:
    provider: qwen_official
  logic:
    provider: deepseek_official
  merge:
    provider: glm_official
```

同时保留 `siliconflow`。目标 Provider 接口包括：

- `siliconflow`
- `deepseek_official`
- `qwen_official`
- `glm_official`

官方模型 API 可改善稳定性和原生 JSON/thinking 参数兼容性，但它仍然只是推理服务，不是事实来源。

### 12.2 Evidence Source

```yaml
evidence_sources:
  rancher_docs:
    adapter: versioned_docs
    domains: [ranchermanager.docs.rancher.com]
  nvd:
    adapter: nvd_api
    domains: [nvd.nist.gov]
  cve_org:
    adapter: cve_api
    domains: [cve.org]
```

Evidence Source 负责来源身份、抓取、缓存、版本和证据审计。Provider 配置不得包含“官方事实可信度”，Evidence Source 配置也不得包含模型参数。

## 13. 输出报告设计

### 13.1 JSON 顶层建议

```yaml
metadata: {}
overall_status: success|degraded|failed
verification_summary:
  coverage_rate: 0.0
  claims_total: 0
  verified: 0
  contradicted: 0
  partially_verified: 0
  not_verified: 0
  conflicting_sources: 0
  version_mismatch: 0
  insufficient_evidence: 0
claims: []
evidence: []
verification_results: []
agent_reviews: []
execution_notes: []
```

### 13.2 每条核验结果

- Claim 原文、位置、类型和规范化文本。
- Verification Status 和确定性检查结果。
- 官方证据标题、片段、URL、检索时间、版本和哈希。
- Fact 解释、Security 意见、Logic 意见和 Merge 裁决。
- 原文、建议改写、修改理由。
- `requires_human_review` 和触发原因。

Markdown 应把 `not_verified` 展示为“未核验/证据不足”，不能使用“错误”“虚假”或“无效”等误导性文字。

## 14. 调用次数与成本模式

不允许每条 Claim 单独调用模型。Claims 按主题和上下文预算分组，例如：架构通信、身份权限、凭据存储、Fleet、CVE/版本。

### 14.1 三种模式

| 模式 | Claim Extraction | Fact Verification | Security | Logic | Merge | 特点 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `budget` | 本地规则 | 1 | 1 | 1 | 1 | 约 4 次；覆盖率较低，保持接近 v0.2 成本 |
| `evidence` | 1 | 1-3 | 1 | 1 | 1 | 约 5-7 次；推荐默认 MVP |
| `full-verification` | 1-2 | 2-3 | 1-2 | 1 | 1 | 约 6-9 次；高价值报告和人工复核场景 |

### 14.2 按报告规模估算

| 报告规模 | Budget | Evidence | Full Verification |
| --- | ---: | ---: | ---: |
| 小报告 | 4 | 5 | 6 |
| 中报告 | 4 | 6 | 7-8 |
| 长报告 | 4 | 7 | 8-9 |

相对于 v0.2 的四次调用，推荐 `evidence` 模式预计增加 1-3 次。在线检索、BM25、向量检索、版本比较、缓存命中和 JSON 校验均是本地或普通 HTTP 操作，不计入模型调用。

每个模式必须设置：最大 Claim 数、每类 Claim 配额、单批 token 上限、Evidence 片段上限、总模型调用上限和运行预算。达到预算时保留未处理 Claim，并标记 `not_verified`，不得静默丢弃。

## 15. 阶段计划

### Phase 1：离线 Schema 与流程

- Claim、Evidence、Evidence Package、Verification Result schema。
- 来源白名单、优先级和产品/组件受控词表。
- 本地 Rancher/Kubernetes/CVE fixture，不联网。
- Claim 规范化、去重、版本过滤和状态规则。
- 假 Retrieval Adapter、Evidence Store 和确定性 Matcher。
- JSON/Markdown 输出草案及审计字段。
- 不修改 v0.2 默认工作流；通过独立 feature flag 或实验入口组装。

### Phase 2：时效性在线证据

- CVE.org、NVD、GitHub Advisory 适配器。
- Rancher/SUSE Security Advisory 和 Release Notes 适配器。
- HTTP 缓存、ETag、限流、超时和快照清单。
- 使用公开小型 fixture 做一次受控真实验证。

### Phase 3：本地官方文档库

- Rancher/SUSE/Kubernetes/Fleet 文档同步器。
- 版本化清洗、分段、BM25 和 embedding 混合索引。
- 架构、通信、Token、RBAC 和组件关系核验。

### Phase 4：Evidence-Aware Review

- Security Evidence Review。
- Fact Evidence Analyst 批处理。
- GLM-5.2 Evidence Judge、Senior Reviewer 和 Final Editor。
- 专家版 Markdown/JSON 报告。

### Phase 5：Benchmark

- Claim 提取 precision/recall。
- 证据召回率和正确匹配率。
- Verification Status 准确率。
- 错误引用率、版本混淆率和无证据误判率。
- 模型调用数、token、耗时、缓存命中率和人工复核成本。

## 16. 风险与缓解

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| 文档版本漂移 | 新版行为错误覆盖旧版报告 | 强制版本元数据和 `version_mismatch` |
| 产品/组件混淆 | RKE2、Fleet、Rancher Manager 证据错配 | 受控组件图谱和确定性过滤 |
| 官方来源冲突 | 自动裁决产生错误结论 | 保留双方快照并标记 `conflicting_sources` |
| 在线服务不稳定 | 长报告核验中断 | 缓存、适配器级超时、断点恢复；不靠模型 retry 掩盖 |
| 搜索结果污染 | 第三方内容进入最终证据 | 域名、组织、仓库和内容类型多重白名单 |
| 文档 Prompt Injection | 页面文本影响 Agent 指令 | Evidence 作为不可信数据转义；禁止执行页面指令 |
| 证据过期 | 旧缓存产生错误状态 | 缓存年龄、刷新策略和 stale 标记 |
| 引用许可与体积 | 无法提交完整页面快照 | 最小片段、哈希、manifest；缓存默认不进 Git |
| Claim 爆炸 | 调用数和成本失控 | 分类配额、优先级、批处理和硬预算 |
| 私有报告外发 | 安全研究材料泄露 | 明确 consent、Provider 审计、本地模式和最小数据发送 |
| LLM 伪造引用 | 报告出现不存在的来源 | 只允许引用 Evidence ID，最终 URL 由本地层渲染 |

## 17. 验收标准

v0.3 MVP 至少满足：

1. Claim 和 Evidence schema 可稳定序列化并保留来源位置。
2. 所有最终证据通过白名单和来源身份校验。
3. 每个 Evidence 具有 URL、检索时间、版本、片段和 SHA-256 哈希。
4. 没有证据时不会输出 `contradicted`。
5. 版本不匹配不会被错误标记为支持或冲突。
6. Rancher Manager、Fleet、RKE、RKE2、Kubernetes 不发生静默混淆。
7. Fact 不使用模型记忆覆盖 Evidence。
8. Security 不自行裁决 CVE 和版本真实性。
9. Logic 不生成外部事实或 URL。
10. Merge 只能引用已存在的 Evidence ID。
11. JSON 和 Markdown 的核验数量、状态和来源一致。
12. 模型调用、检索请求、缓存命中和失败均可审计。
13. `not_verified` 在任何输出中都不显示为错误。
14. Phase 1 全部测试离线运行，不访问网络或真实模型。

## 18. Phase 1 最小任务清单

1. 冻结 Claim、Evidence、Evidence Package、Verification Result schema 草案。
2. 建立产品和组件受控词表，以及 Claim Type 到 Evidence Source 的路由表。
3. 定义官方来源 Policy：域名、GitHub 组织/仓库、来源优先级和禁止来源。
4. 创建 15-25 个脱敏离线 fixture，覆盖支持、冲突、版本不匹配、证据不足和来源冲突。
5. 实现 Markdown Section 数据结构和行号保持测试。
6. 实现 Claim 规范化和确定性去重接口。
7. 实现 `FixtureEvidenceSource` 与内存 Evidence Store。
8. 实现产品、组件、版本、CVE ID 的确定性 Matcher。
9. 实现 Verification Status 规则引擎，不接 LLM。
10. 设计 Fact Evidence Analyst 的批量输入/输出契约，不调用真实 Provider。
11. 设计 Security/Logic/Merge 的新 Prompt 契约和 fake response 测试。
12. 设计证据版 `review.json` 和 `review.md` golden fixtures。
13. 增加调用预算对象，确保 fixture 流程不会按 Claim 单独调用。
14. 定义 run registry 的检索、缓存、证据和调用审计字段。
15. 完成 Phase 1 架构评审后，再决定 Phase 2 的 HTTP 客户端和缓存实现。

## 19. Release Gate

Phase 1 完成不代表 v0.3 可发布。进入真实在线验证前必须单独确认：

- 来源服务条款、缓存许可和 User-Agent 策略。
- 私有报告外发授权与最小化策略。
- 在线 Adapter 的限流、超时和重试预算。
- Evidence 快照是否包含敏感查询或报告原文。
- LLM Provider 与 Evidence Source 配置已完全分离。
- 真实验证不会覆盖 v0.2 输出，也不会改变 v0.2 默认四调用工作流。
