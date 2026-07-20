# Raw Evidence Collection Status

## Scope

第一阶段只覆盖：

- Cluster Agent
- Reverse Tunnel
- Kubernetes RBAC
- ServiceAccount
- Registration Token / API Token

所有 raw 文件必须来自可追溯的官方原始页面或官方源码快照，并在同级 metadata 中记录：`source_name`、`official_url`、`title`、`related_claim_ids`。本目录不接受搜索摘要、博客、报告 `input.md` 或未经核验的复制内容。

## Directory layout

```text
raw/
├── rancher/      # Rancher official documentation
├── kubernetes/   # Kubernetes official documentation
└── source/       # Official source repositories / source snapshots
```

## Current collection state

当前 raw 目录只建立了分类目录，尚未写入任何原始资料快照：

- Confirmed raw documents：0
- Confirmed raw source files：0
- Evidence chunks created：0
- Network/model calls：0

因此当前没有任何资料可被当作 evidence 使用，也没有用报告正文或摘要替代原文。

## Registered sources and intended coverage

来源入口已登记在 `../source-catalog.md`，后续收集范围如下：

| Raw location | Source family | Intended coverage | Related Claim scope |
| --- | --- | --- | --- |
| `raw/rancher/` | Rancher official documentation | Cluster Agent、Agent communication、Imported cluster、Reverse Tunnel、Token、API interaction | P0 Cluster Agent / Reverse Tunnel / Token / architecture Claims |
| `raw/kubernetes/` | Kubernetes official documentation | RBAC、ServiceAccount、Authentication | P0 RBAC / ServiceAccount / Token Claims |
| `raw/source/` | `rancher/rancher`、`rancher/remotedialer`、`rancher/system-agent` | Agent、Tunnel、API 和权限实现 | P0 Cluster Agent / Reverse Tunnel / architecture Claims |

## Missing sources

仍缺少：

1. 具体官方页面或源码版本快照，以及可审计的抓取时间。
2. 每份原始资料对应的 `related_claim_ids` 清单。
3. 文档标题、版本、官方 URL 和稳定 raw 文件名。
4. 从原始资料生成的 `chunk_id`、原文片段和来源位置。

在这些字段补齐前，`evidence-collection-plan.json` 中对应记录保持 `pending`，不得进入事实验证结果。

## Collection rule

后续每个 raw 资料应以原文或可审计源码快照保存，并附 metadata；不得把 README、人工摘要或模型输出作为 raw evidence。
