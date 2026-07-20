# Rancher Security Review v1 Evidence Source Catalog

## Scope and status

本目录只登记可追溯的官方来源入口和后续证据收集范围，不包含搜索摘要、报告原文或人工生成的 evidence。当前目录记录的是 source catalog，不代表对应内容已经抓取或已经支持任何 Claim；具体页面、版本和 `chunk_id` 仍需后续离线采集与审计。

## Rancher Official Documentation

官方入口：<https://ranchermanager.docs.rancher.com/>

| source_name | official_url | related_claim_type | evidence_role | priority |
| --- | --- | --- | --- | --- |
| Rancher Manager Cluster Agent documentation | https://ranchermanager.docs.rancher.com/ | `cluster_agent` | Cluster Agent 部署、职责和生命周期的 primary documentation | P0 |
| Rancher Manager Agent communication documentation | https://ranchermanager.docs.rancher.com/ | `cluster_agent`, `reverse_tunnel` | Agent 与 Rancher Server 通信路径的 primary documentation | P0 |
| Rancher Manager imported cluster documentation | https://ranchermanager.docs.rancher.com/ | `cluster_agent`, `serviceaccount_token`, `rancher_architecture` | Imported cluster 接入流程和资源边界的 primary documentation | P0 |
| Rancher Manager network / tunnel documentation | https://ranchermanager.docs.rancher.com/ | `reverse_tunnel` | Reverse Tunnel 的产品行为和网络约束的 primary documentation | P0 |
| Rancher Manager authorization documentation | https://ranchermanager.docs.rancher.com/ | `kubernetes_rbac` | Rancher 角色与权限模型的 primary documentation | P0 |
| Rancher Manager token documentation | https://ranchermanager.docs.rancher.com/ | `serviceaccount_token` | API Token、Registration Token 生命周期和使用场景的 primary documentation | P0 |
| Rancher Manager credential documentation | https://ranchermanager.docs.rancher.com/ | `credential_management`, `cloud_credential` | Credential、Secret 和云凭证行为的 primary documentation | P0 |
| Rancher Manager API documentation | https://ranchermanager.docs.rancher.com/ | `rancher_architecture`, `cluster_agent` | Rancher Server API 与下游资源交互的 primary documentation | P0 |

上述记录使用官方文档根 URL；在没有网络访问和版本快照的情况下，不将未确认的具体页面路径写入目录。

## Rancher Official Source Code

| source_name | official_url | related_claim_type | evidence_role | priority |
| --- | --- | --- | --- | --- |
| rancher/rancher | https://github.com/rancher/rancher | `rancher_architecture`, `cluster_agent`, `kubernetes_rbac`, `serviceaccount_token`, `credential_management` | 产品实现、API、权限和资源定义的 primary source code | P0 |
| rancher/remotedialer | https://github.com/rancher/remotedialer | `reverse_tunnel`, `cluster_agent` | Remotedialer/tunnel 建立和转发实现的 primary source code | P0 |
| rancher/system-agent | https://github.com/rancher/system-agent | `cluster_agent`, `rancher_architecture` | Agent 安装、启动和节点侧执行行为的 primary source code | P0 |

源码只能支持实际存在于对应版本和路径中的实现事实；未定位到具体 commit、文件或行号前，不生成 evidence chunk。

## Kubernetes Official Documentation

| source_name | official_url | related_claim_type | evidence_role | priority |
| --- | --- | --- | --- | --- |
| Kubernetes RBAC documentation | https://kubernetes.io/docs/reference/access-authn-authz/rbac/ | `kubernetes_rbac` | Kubernetes Role、RoleBinding 和权限授权规则的 primary documentation | P0 |
| Kubernetes Service Accounts documentation | https://kubernetes.io/docs/concepts/security/service-accounts/ | `serviceaccount_token`, `kubernetes_rbac` | ServiceAccount 身份和 Token 使用规则的 primary documentation | P0 |
| Kubernetes Authentication documentation | https://kubernetes.io/docs/reference/access-authn-authz/authentication/ | `serviceaccount_token`, `rancher_architecture` | Kubernetes API authentication 机制的 primary documentation | P0 |

## RKE2 Official Documentation

| source_name | official_url | related_claim_type | evidence_role | priority |
| --- | --- | --- | --- | --- |
| RKE2 security documentation | https://docs.rke2.io/ | `rke2_security` | RKE2 安全能力和配置的 primary documentation；具体主题页面待定位 | P1 |
| RKE2 CIS hardening documentation | https://docs.rke2.io/ | `rke2_security` | CIS 加固配置和验证的 primary documentation；具体主题页面待定位 | P1 |
| RKE2 FIPS documentation | https://docs.rke2.io/ | `rke2_security` | FIPS 支持和适用边界的 primary documentation；具体主题页面待定位 | P1 |

## Security Advisory Sources

| source_name | official_url | related_claim_type | evidence_role | priority |
| --- | --- | --- | --- | --- |
| SUSE security advisories | https://www.suse.com/security/cve/ | `cve_security`, `rke2_security` | SUSE/Rancher 安全公告、受影响版本和修复信息的 primary advisory | P1 |
| Rancher GitHub security advisories | https://github.com/rancher/rancher/security/advisories | `cve_security` | Rancher 项目发布的安全公告和修复上下文 | P1 |
| GitHub Security Advisories / GHSA | https://github.com/advisories | `cve_security` | GHSA 标识和上游安全公告的 secondary advisory | P1 |
| NVD | https://nvd.nist.gov/vuln | `cve_security` | CVE 元数据和影响范围的 secondary advisory | P1 |

## P2 sources

当前没有登记 P2 来源。CNCF、CISA、NSA 等来源只有在明确支持某条 Claim、且 P0/P1 来源不足时，才作为补充交叉来源；不能替代产品官方文档、源码或厂商安全公告。

## Catalog statistics

- Source records: 21
- P0 records：14（8 Rancher documentation + 3 Rancher repositories + 3 Kubernetes documentation）
- P1 records: 7 (3 RKE2 documentation + 4 security advisory entries)
- P2 records：0
- Actual evidence chunks：0
- Network/model calls：0

All records still require later localization of the exact page, version, and auditable text.
