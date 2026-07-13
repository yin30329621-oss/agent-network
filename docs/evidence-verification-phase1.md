# Agent Network v0.3 Phase 1: Offline Evidence Verification

## 目标

Phase 1 实现完全离线、确定性、可复现的证据核验基础设施。它不调用 Fact、Security、Logic、Merge，不访问网络，也不代表真实官方核验。

> Phase 1 使用人为构造的 fixture。fixture 中的片段和 URL 不是官方证据，不得用于真实安全结论。

## 数据结构

### Claim

Claim 保留来源文件、章节、行号、原文、规范化声明、类型、实体、产品、组件、版本范围、核验优先级和是否需要外部证据。

核心类型覆盖架构行为、通信、认证授权、凭据存储、Token 生命周期、Kubernetes 行为、Rancher 功能、版本、CVE、CVSS、安全建议和术语。

### Evidence

Evidence 保留来源类型、标题、URL、声明的官方域名、检索时间、文档版本、原始证据片段、SHA-256 片段哈希、相关度、来源优先级和支持/反驳方向。

Phase 1 额外记录产品、组件、适用 Claim 类型、关键词、覆盖范围和 `fixture_only`。`excerpt_hash` 由规范化后的原始片段确定性计算。

### Verification Result

Verification Result 包含核验状态、报告原文、官方值、支持/反驳 Evidence ID、证据强度、版本匹配、判定解释、人工复核标记、时间和完整匹配原因。

## 状态规则

| 条件 | 状态 |
| --- | --- |
| 不需要外部证据 | `not_applicable` |
| 没有 Evidence | `not_verified` |
| 候选相关性或范围不足 | `insufficient_evidence` |
| 只有完整支持证据 | `verified` |
| 只有反驳证据 | `contradicted` |
| 只有部分覆盖的支持证据 | `partially_verified` |
| 同时支持和反驳 | `conflicting_sources` |
| 产品/组件匹配但版本不匹配 | `version_mismatch` |

`not_verified` 永远不能自动转换为 `contradicted`。

## Fixture

目录：`benchmarks/fixtures/evidence-v1/`

数据集包含 Cluster Agent、WebSocket、Reverse Tunnel、ServiceAccount Token、Registration Token、RBAC、Fleet Bundle、Cloud Credential，以及虚构的 `CVE-2099-0001`。所有片段包含 `FIXTURE ONLY`，URL 使用 `.invalid` 保留域。

## Fake Evidence Source

`FakeEvidenceSource.search(claim)` 只读取内存中的 fixture Evidence，并根据 Claim ID、产品、组件和关键词返回稳定排序的候选项。`network_request_count` 固定为 0。

Phase 2 的真实 Source 将实现相同的 `search(claim) -> list[Evidence]` 接口，并负责白名单、HTTP 审计、缓存、限流和快照。

## Matcher

Matcher 不使用 embedding，依次记录：

- 产品是否一致
- 组件是否一致
- Claim Type 是否适用
- 版本范围是否一致
- 关键词重合度
- 原始和有效相关度
- 来源优先级
- 拒绝原因

产品、组件或 Claim Type 不匹配时不能成为有效支持证据。Rancher Manager、Fleet、RKE、RKE2 等产品使用独立 canonical ID。

## CLI

运行全部 fixture：

```text
uv run agent-network verify-evidence benchmarks/fixtures/evidence-v1 --output outputs/evidence-phase1
```

运行单个 Claim：

```text
uv run agent-network verify-evidence benchmarks/fixtures/evidence-v1 --claim claim-cve-exists --format json --output outputs/evidence-one
```

支持 `json`、`markdown`、`both`。输出包括 `verification.json`、`verification.md`（按格式选择）和始终生成的 `run.json`。

## 审计

`run.json` 明确记录：

- `mode=offline_fixture`
- fixture 路径与 Claim 过滤条件
- Claim、Evidence 和状态数量
- `model_call_count=0`
- `network_request_count=0`
- 输出文件路径

## 局限性

- fixture 不是官方资料，不能据此修改真实 Rancher 报告。
- Claim 由人工提供，尚无自动 Claim Extraction。
- 关键词匹配不具备语义检索能力。
- 版本比较仅覆盖 Phase 1 所需的数字版本范围。
- 没有在线缓存、文档快照、BM25 或向量索引。
- 尚未接入四 Agent 工作流。

## Phase 2

Phase 2 应优先增加 CVE.org、NVD、GitHub Advisory、Rancher/SUSE Security Advisory 和 Release Notes Source。真实 Source 必须复用当前 Schema 和 Source 接口，并增加官方域名校验、ETag/Last-Modified、本地缓存、内容哈希、限流和网络请求审计。
