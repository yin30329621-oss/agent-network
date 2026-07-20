# Evidence Library v1 Pending Sources

## Collection status

当前仅完成目录初始化和来源登记，未将网页正文、源码快照或安全公告正文保存为 raw evidence。搜索结果摘要、`input.md` 和人工生成的摘要均未写入 evidence library。

- Saved raw documents: 0
- Saved source snapshots: 0
- Saved advisories: 0
- Network/model calls recorded by repository: 0
- Status: `pending`

每个来源在能够保存原始内容后，必须生成带 front matter 的文件：

```yaml
source_name:
source_type:
official_url:
title:
version:
related_claim_types:
```

## Rancher official documentation

```yaml
source_name: Rancher Manager official documentation
source_type: official_document
official_url: https://ranchermanager.docs.rancher.com/
title: Cluster Agent, Fleet Agent, Agent communication, Reverse Tunnel, WebSocket/remotedialer, Imported Cluster, RBAC, API Token, Registration Token, Cloud Credential, Webhook
version: pending
related_claim_types: [cluster_agent, reverse_tunnel, rancher_architecture, kubernetes_rbac, serviceaccount_token, cloud_credential, webhook, fleet_management]
collection_status: pending
```

缺失：具体页面路径、页面版本、原文快照和可审计的抓取时间。

## Rancher official source

| source_name | official_url | related_claim_types | status |
| --- | --- | --- | --- |
| rancher/rancher | https://github.com/rancher/rancher | `rancher_architecture`, `cluster_agent`, `authentication`, `authorization` | pending |
| rancher/remotedialer | https://github.com/rancher/remotedialer | `reverse_tunnel`, `websocket`, `cluster_agent` | pending |
| rancher/system-agent | https://github.com/rancher/system-agent | `cluster_agent`, `agent_communication` | pending |
| rancher/webhook | https://github.com/rancher/webhook | `webhook`, `authorization` | pending |

缺失：固定 commit/tag、具体文件路径、源码原文和许可证/版本记录。

## Kubernetes official documentation

```yaml
source_name: Kubernetes Authentication
source_type: official_document
official_url: https://kubernetes.io/docs/reference/access-authn-authz/authentication/
title: Authenticating
version: pending
related_claim_types: [authentication, serviceaccount_token]
collection_status: pending
```

```yaml
source_name: Kubernetes Service Accounts
source_type: official_document
official_url: https://kubernetes.io/docs/concepts/security/service-accounts/
title: Service Accounts
version: pending
related_claim_types: [serviceaccount_token, kubernetes_rbac, secret]
collection_status: pending
```

```yaml
source_name: Kubernetes RBAC
source_type: official_document
official_url: https://kubernetes.io/docs/reference/access-authn-authz/rbac/
title: Using RBAC Authorization
version: pending
related_claim_types: [kubernetes_rbac, role, clusterrole, rolebinding, clusterrolebinding, secret]
collection_status: pending
```

## RKE2 official documentation

```yaml
source_name: RKE2 official documentation
source_type: official_document
official_url: https://docs.rke2.io/
title: Security, CIS, FIPS, and hardening
version: pending
related_claim_types: [rke2_security]
collection_status: pending
```

缺失：Security/CIS/FIPS/Hardening 的具体页面、版本化正文和原始快照。

## Security sources

| source_name | official_url | related_claim_types | status |
| --- | --- | --- | --- |
| SUSE security advisories | https://www.suse.com/security/cve/ | `cve_security`, `rke2_security` | pending |
| Rancher GitHub security advisories | https://github.com/rancher/rancher/security/advisories | `cve_security` | pending |
| GitHub Security Advisories / GHSA | https://github.com/advisories | `cve_security` | pending |
| NVD | https://nvd.nist.gov/vuln | `cve_security` | pending |

缺失：具体 advisory ID、受影响版本、修复版本和公告原文。

## Why these sources remain pending

当前工作区没有已核验的原始页面或源码快照可直接纳入 library。后续必须先保存原文，再按 `claim_id` 建立 metadata 和 chunk；在此之前不生成 evidence fixture，也不把本文件中的来源登记视为 evidence。
