## Prioritized Revision Plan

Each priority item is rendered as a card to keep the actionable revision visible in GitHub and VS Code previews. Full source locations remain in the Claim appendix.

Deduplication groups findings when Claim ID sets match and issue/suggestion similarity is at least 0.72. Sources and source finding IDs are retained; original JSON findings are unchanged.

### Priority 1 — high

- **Section:** 3.2.4 Data Store（数据存储）
- **Source location:** input.md#rancher.3-2-管理平面-management-plane.3-2-4-data-store-数据存储:paragraph-119:L200-L200, input.md#rancher.3-2-管理平面-management-plane.3-2-4-data-store-数据存储:table_row-129:L214-L214
- **Claim IDs:** claim-235a797973d69fad, claim-dfe9bd4c30fe9871
- **Reviewer signals:** claim-235a797973d69fad: partially_supported/unsupported; claim-dfe9bd4c30fe9871: partially_supported/partially_supported
- **Current issue:** 报告声称Data Store存储凭证等敏感数据，但未讨论静态加密等保护措施，论证不完整。
- **Required evidence:** needs_external_verification: Rancher管理集群etcd encryption at rest配置及Secret加密状态。
- **Recommended revision:** 补充etcd静态加密及Secret加密的说明。
- **Sources:** security, logic, merge
- **Source finding IDs:** finding-4dde6f354606, finding-a5955fd74209

### Priority 2 — high

- **Section:** 3.3.1 Cluster Agent
- **Source location:** input.md#rancher.3-3-集群通信平面-cluster-communication-plane.3-3-1-cluster-agent:table_row-140:L234-L234, input.md#rancher.3-3-集群通信平面-cluster-communication-plane.3-3-1-cluster-agent:paragraph-137:L229-L229
- **Claim IDs:** claim-8a20421aa3a005eb, claim-fdb6477afdb5dc04
- **Reviewer signals:** claim-8a20421aa3a005eb: partially_supported/unsupported; claim-fdb6477afdb5dc04: partially_supported/unsupported
- **Current issue:** 报告描述Cluster Agent通过ServiceAccount访问Kubernetes API，但未明确RBAC最小权限范围，论证不充分。
- **Required evidence:** needs_external_verification: cattle-cluster-agent ServiceAccount的ClusterRole权限详情。
- **Recommended revision:** 明确Agent所需的最小权限集，并建议审计。
- **Sources:** security, logic, merge
- **Source finding IDs:** finding-1e9ed33d8b6f, finding-a8698f1d1829

### Priority 3 — medium

- **Section:** 3.3.2 集群通信中的身份凭证
- **Source location:** input.md#rancher.3-3-集群通信平面-cluster-communication-plane.3-3-2-集群通信中的身份凭证:paragraph-145:L240-L240
- **Claim IDs:** claim-4e5a6e18fd06091d
- **Reviewer signals:** claim-4e5a6e18fd06091d: unknown/unsupported
- **Current issue:** 报告提到Registration Token用于集群注册，但未说明Token有效期、传输安全及撤销机制，论证缺失。
- **Required evidence:** needs_external_verification: Registration Token生命周期策略及导入清单分发渠道的安全配置。
- **Recommended revision:** 补充Token有效期、一次性使用及安全分发建议。
- **Sources:** security, logic, merge
- **Source finding IDs:** finding-5067c978211e, finding-7e8c6d572151

### Priority 4 — medium

- **Section:** 1. 主要功能
- **Source location:** input.md#rancher.1-主要功能:paragraph-47:L64-L64
- **Claim IDs:** claim-3a5bd3fd2b1fd13a
- **Reviewer signals:** claim-3a5bd3fd2b1fd13a: partially_supported/partially_supported
- **Current issue:** 报告声称支持多种认证方式，但验证证据仅覆盖Active Directory，逻辑跳跃。
- **Required evidence:** needs_external_verification: 其他认证方式（LDAP, GitHub, SAML, OIDC）的官方支持声明。
- **Recommended revision:** 为每种认证方式提供引用或缩小声明范围。
- **Sources:** logic, merge
- **Source finding IDs:** finding-184da05c0d39

### Priority 5 — low

- **Section:** 3.2.2 Rancher API Server
- **Source location:** input.md#rancher.3-2-管理平面-management-plane.3-2-2-rancher-api-server:paragraph-103:L174-L174
- **Claim IDs:** claim-5dd455aa1d3e5489
- **Reviewer signals:** claim-5dd455aa1d3e5489: partially_supported/unsupported
- **Current issue:** 报告描述Rancher API Server为核心组件，但验证证据仅涉及Authentication Proxy，论证不匹配。
- **Required evidence:** needs_external_verification: Rancher API Server架构文档。
- **Recommended revision:** 确保证据直接支持声明，或调整声明以匹配证据。
- **Sources:** logic, merge
- **Source finding IDs:** finding-1e1c1a931dec

### Priority 6 — low

- **Section:** 6.1 典型漏洞概览
- **Source location:** input.md#rancher.6-1-典型漏洞概览:table_row-289:L561-L561
- **Claim IDs:** claim-07ab6a2242540b6a
- **Reviewer signals:** claim-07ab6a2242540b6a: unknown/unsupported
- **Current issue:** 报告引用CVE-2026-41053并给出修复版本，但验证证据显示不相关且版本过时，存在矛盾。
- **Required evidence:** needs_external_verification: CVE-2026-41053的官方详情及受影响版本。
- **Recommended revision:** 核实CVE编号和修复版本，或移除不准确引用。
- **Sources:** logic, merge
- **Source finding IDs:** finding-294f7854d9fb

### Priority 7 — info

- **Section:** 3.1 Rancher 软件架构概述; 3.2 管理平面（Management Plane）
- **Source location:** input.md#rancher.3-1-rancher-软件架构概述:paragraph-81:L129-L130, input.md#rancher.3-2-管理平面-management-plane:paragraph-88:L144-L144
- **Claim IDs:** claim-a430ef3fb491d40b, claim-ad51af831ebb77ac
- **Reviewer signals:** claim-a430ef3fb491d40b: partially_supported/unsupported; claim-ad51af831ebb77ac: partially_supported/unsupported
- **Current issue:** 多个架构声明被验证为unsupported，表明报告可能基于不充分或无关证据。
- **Required evidence:** needs_external_verification: 各组件架构的官方文档。
- **Recommended revision:** 重新审查证据来源，确保每个声明有直接支持。
- **Sources:** logic, merge
- **Source finding IDs:** finding-f9e694f629c2
