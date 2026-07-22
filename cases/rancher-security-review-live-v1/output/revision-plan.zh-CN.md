## 优先修改计划

以下采用卡片式布局，便于在 GitHub 和 VS Code 预览中阅读；完整 source_location 保留在 Claim 审计附录。

去重规则：Claim ID 集合相同且 issue/suggestion 相似度至少为 0.72；保留来源和 source finding ID，不修改原始 JSON findings。

### 优先级 1 — high

- **章节：** 3.2.4 Data Store（数据存储）
- **原文位置：** input.md#rancher.3-2-管理平面-management-plane.3-2-4-data-store-数据存储:paragraph-119:L200-L200, input.md#rancher.3-2-管理平面-management-plane.3-2-4-data-store-数据存储:table_row-129:L214-L214
- **Claim IDs：** claim-235a797973d69fad, claim-dfe9bd4c30fe9871
- **Reviewer 信号：** claim-235a797973d69fad：部分支持 (partially_supported)/不支持 (unsupported)；claim-dfe9bd4c30fe9871：部分支持 (partially_supported)/部分支持 (partially_supported)
- **当前问题：** 报告声称Data Store存储凭证等敏感数据，但未讨论静态加密等保护措施，论证不完整。
- **所需证据：** needs_external_verification: Rancher管理集群etcd encryption at rest配置及Secret加密状态。
- **建议修改：** 补充etcd静态加密及Secret加密的说明。
- **建议动作：** 需要人工复核
- **来源：** security, logic, merge
- **来源 finding IDs：** finding-4dde6f354606, finding-a5955fd74209

### 优先级 2 — high

- **章节：** 3.3.1 Cluster Agent
- **原文位置：** input.md#rancher.3-3-集群通信平面-cluster-communication-plane.3-3-1-cluster-agent:table_row-140:L234-L234, input.md#rancher.3-3-集群通信平面-cluster-communication-plane.3-3-1-cluster-agent:paragraph-137:L229-L229
- **Claim IDs：** claim-8a20421aa3a005eb, claim-fdb6477afdb5dc04
- **Reviewer 信号：** claim-8a20421aa3a005eb：部分支持 (partially_supported)/不支持 (unsupported)；claim-fdb6477afdb5dc04：部分支持 (partially_supported)/不支持 (unsupported)
- **当前问题：** 报告描述Cluster Agent通过ServiceAccount访问Kubernetes API，但未明确RBAC最小权限范围，论证不充分。
- **所需证据：** needs_external_verification: cattle-cluster-agent ServiceAccount的ClusterRole权限详情。
- **建议修改：** 明确Agent所需的最小权限集，并建议审计。
- **建议动作：** 需要人工复核
- **来源：** security, logic, merge
- **来源 finding IDs：** finding-1e9ed33d8b6f, finding-a8698f1d1829

### 优先级 3 — medium

- **章节：** 3.3.2 集群通信中的身份凭证
- **原文位置：** input.md#rancher.3-3-集群通信平面-cluster-communication-plane.3-3-2-集群通信中的身份凭证:paragraph-145:L240-L240
- **Claim IDs：** claim-4e5a6e18fd06091d
- **Reviewer 信号：** claim-4e5a6e18fd06091d：未知 (unknown)/不支持 (unsupported)
- **当前问题：** 报告提到Registration Token用于集群注册，但未说明Token有效期、传输安全及撤销机制，论证缺失。
- **所需证据：** needs_external_verification: Registration Token生命周期策略及导入清单分发渠道的安全配置。
- **建议修改：** 补充Token有效期、一次性使用及安全分发建议。
- **建议动作：** 需要人工复核
- **来源：** security, logic, merge
- **来源 finding IDs：** finding-5067c978211e, finding-7e8c6d572151

### 优先级 4 — medium

- **章节：** 1. 主要功能
- **原文位置：** input.md#rancher.1-主要功能:paragraph-47:L64-L64
- **Claim IDs：** claim-3a5bd3fd2b1fd13a
- **Reviewer 信号：** claim-3a5bd3fd2b1fd13a：部分支持 (partially_supported)/部分支持 (partially_supported)
- **当前问题：** 报告声称支持多种认证方式，但验证证据仅覆盖Active Directory，逻辑跳跃。
- **所需证据：** needs_external_verification: 其他认证方式（LDAP, GitHub, SAML, OIDC）的官方支持声明。
- **建议修改：** 为每种认证方式提供引用或缩小声明范围。
- **建议动作：** 补充证据
- **来源：** logic, merge
- **来源 finding IDs：** finding-184da05c0d39

### 优先级 5 — low

- **章节：** 3.2.2 Rancher API Server
- **原文位置：** input.md#rancher.3-2-管理平面-management-plane.3-2-2-rancher-api-server:paragraph-103:L174-L174
- **Claim IDs：** claim-5dd455aa1d3e5489
- **Reviewer 信号：** claim-5dd455aa1d3e5489：部分支持 (partially_supported)/不支持 (unsupported)
- **当前问题：** 报告描述Rancher API Server为核心组件，但验证证据仅涉及Authentication Proxy，论证不匹配。
- **所需证据：** needs_external_verification: Rancher API Server架构文档。
- **建议修改：** 确保证据直接支持声明，或调整声明以匹配证据。
- **建议动作：** 需要人工复核
- **来源：** logic, merge
- **来源 finding IDs：** finding-1e1c1a931dec

### 优先级 6 — low

- **章节：** 6.1 典型漏洞概览
- **原文位置：** input.md#rancher.6-1-典型漏洞概览:table_row-289:L561-L561
- **Claim IDs：** claim-07ab6a2242540b6a
- **Reviewer 信号：** claim-07ab6a2242540b6a：未知 (unknown)/不支持 (unsupported)
- **当前问题：** 报告引用CVE-2026-41053并给出修复版本，但验证证据显示不相关且版本过时，存在矛盾。
- **所需证据：** needs_external_verification: CVE-2026-41053的官方详情及受影响版本。
- **建议修改：** 核实CVE编号和修复版本，或移除不准确引用。
- **建议动作：** 需要人工复核
- **来源：** logic, merge
- **来源 finding IDs：** finding-294f7854d9fb

### 优先级 7 — info

- **章节：** 3.1 Rancher 软件架构概述; 3.2 管理平面（Management Plane）
- **原文位置：** input.md#rancher.3-1-rancher-软件架构概述:paragraph-81:L129-L130, input.md#rancher.3-2-管理平面-management-plane:paragraph-88:L144-L144
- **Claim IDs：** claim-a430ef3fb491d40b, claim-ad51af831ebb77ac
- **Reviewer 信号：** claim-a430ef3fb491d40b：部分支持 (partially_supported)/不支持 (unsupported)；claim-ad51af831ebb77ac：部分支持 (partially_supported)/不支持 (unsupported)
- **当前问题：** 多个架构声明被验证为unsupported，表明报告可能基于不充分或无关证据。
- **所需证据：** needs_external_verification: 各组件架构的官方文档。
- **建议修改：** 重新审查证据来源，确保每个声明有直接支持。
- **建议动作：** 需要人工复核
- **来源：** logic, merge
- **来源 finding IDs：** finding-f9e694f629c2
