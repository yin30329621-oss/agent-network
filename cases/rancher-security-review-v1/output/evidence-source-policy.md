# Rancher Security Review v1 Evidence Source Policy

## Scope

本策略针对本案例人工筛选后的 64 个 Claim。分类按 Claim 文本主题统计，允许一个 Claim 同时属于多个类别，因此各类别数量不可直接相加。

当前 `cases/rancher-security-review-v1/` 尚未提供本地 evidence chunk fixture；以下内容是来源选择规则，不代表 evidence 已经获取或验证完成。

## Claim 分类统计

| Claim category | Claim 数量 |
| --- | ---: |
| rancher_architecture / Server / downstream API | 42 |
| cluster_agent | 36 |
| kubernetes_rbac | 21 |
| serviceaccount_token / registration token / API token | 21 |
| reverse_tunnel | 13 |
| cloud_credential | 9 |
| cve_security | 8 |
| rke2_security | 2 |
| webhook | 1 |
| 合计（去重 Claim） | 64 |

## Evidence 来源优先级

| Claim Type | Preferred Evidence | Secondary Evidence | 每 Claim 估计数量 |
| --- | --- | --- | ---: |
| rancher_architecture | Rancher 官方架构与组件文档 | Rancher 官方源码/版本化 API 文档 | 1–2 |
| cluster_agent | Rancher 官方 Cluster Agent、下游集群和安装文档 | Rancher 官方源码与发布文档 | 1–2 |
| reverse_tunnel | Rancher 官方网络与 Agent 通信文档 | Rancher 官方源码、配置参考和安全文档 | 1–2 |
| kubernetes_rbac | Kubernetes 官方 RBAC、ServiceAccount 文档 | Rancher 官方权限模型文档 | 1–2 |
| serviceaccount_token | Kubernetes 官方 ServiceAccount/Token 文档；Rancher 官方注册文档 | Rancher 官方源码和配置参考 | 1–2 |
| credential_management | Rancher 官方凭证、Secret 和审计文档 | Kubernetes 官方 Secret 文档 | 1–2 |
| cloud_credential | Rancher 官方 Cloud Credential 与云驱动文档 | 对应云厂商官方 IAM/凭证文档 | 1–2 |
| webhook | Rancher 官方 Webhook/Fleet 文档 | Rancher 官方源码与版本发布说明 | 1–2 |
| rke2_security | RKE2 官方安全、FIPS、CIS 和加固文档 | SUSE/Rancher 官方安全公告 | 2 |
| cve_security | SUSE/Rancher 官方安全公告和修复说明 | NVD、GHSA 及上游项目公告 | 2–3 |

“Preferred Evidence”用于事实判断；Secondary Evidence 只能补充或交叉核对，不能在缺少首选来源时自动升级为已验证。

## Evidence 组合规则

1. 每条 Claim 至少需要一个能直接支持该 Claim 的 evidence chunk；架构、通信和权限 Claim 应优先选择包含明确主体、动作和对象的段落。
2. 一个 chunk 可以支持多个 Claim，但每个 Claim 的 citation 必须明确指向该 chunk，不能只引用文档级 URL。
3. CVE Claim 至少需要漏洞标识、受影响范围/组件和修复或缓解信息中的两个独立事实片段；版本结论必须以对应公告为准。
4. 来源、版本和产品范围不一致时，保留 `version_mismatch` 或 `conflicting_evidence`，不得由 adapter 覆盖 EvidenceDecision 状态。
5. 搜索结果摘要、博客、论坛、未经确认的报告复述和模型生成内容不作为首选 evidence。
6. 不把报告原文自动当作外部 evidence；报告只提供待验证 Claim 的来源上下文。

## 当前 evidence 数量估计

按类别分别估计，若简单相加会重复计算同一 Claim。按 64 个去重 Claim 计算，第一轮建议目标为 **64–96 个 evidence chunk**，即平均每条 Claim 1–1.5 个直接相关 chunk：

- 架构、Cluster Agent、Reverse Tunnel：每条 1 个主来源 chunk，争议项再补 1 个交叉来源。
- RBAC、ServiceAccount 和 Token：每条 1 个 Kubernetes 或 Rancher 规范 chunk；涉及注册流程或权限映射时补 1 个 Rancher chunk。
- Cloud Credential、Webhook：每条 1 个产品行为 chunk，涉及权限或存储风险时补 1 个安全控制 chunk。
- RKE2：每条至少 2 个 chunk，分别覆盖产品/版本事实和安全能力或合规说明。
- CVE：每条 2–3 个 chunk，覆盖官方公告、影响范围和修复建议；不以单一第三方条目完成核验。

## 当前缺失项

- 缺少与 64 个 Claim 对齐的本地 `chunks.json` 或等价离线 evidence catalog。
- 尚未建立 Claim 到官方文档、版本和 chunk_id 的映射。
- 尚未为 CVE、安全公告和 RKE2 文档建立固定的版本快照。
- 尚未补齐 Cloud Credential、Webhook 和 Reverse Tunnel 的产品版本边界。
- 当前离线 runner 因无本地 evidence fixture 会产生 `insufficient_evidence`，不能作为事实验证结果。

## 后续补齐顺序

先建立官方来源 catalog 和可审计的 chunk 快照，再按 `claim_id` 生成 retrieval 结果；优先补齐 Cluster Agent/Reverse Tunnel、RBAC/Token、Cloud Credential 和 CVE 高风险 Claim，最后处理架构背景与低优先级 Claim。所有新增 evidence 必须保留来源、版本、URL 和稳定 `chunk_id`，并通过现有 Evidence Adapter 与 EvidenceDecisionEngine 进入后续流程。
