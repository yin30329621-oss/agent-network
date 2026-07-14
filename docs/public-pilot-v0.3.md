# Agent Network v0.3 Public Pilot Baseline

## 目标与范围

本 Pilot 验证公开 Claim 在官方缓存 Evidence 上经过单批双 Fact Review、引用校验和本地 Reconciliation 的可审计链路。范围限定为三个公开 Claim、现有本地官方缓存和两个独立 Reviewer；不执行 Security、Logic、Merge 或后续 Part 3 以外的扩展流程。

## Provider 与模型

- Fact A：`deepseek_official / deepseek-v4-pro`
- Fact B：`dashscope_official / qwen3.7-plus`

两者接收完全相同的 Claim、Evidence 和 Verification Engine 初判，使用相同的单批边界。Fact A/B 彼此不可见对方输出、引用或推理。不存在逐 Claim 模型调用；每个 Reviewer 各执行一次批量调用。

## Pilot 结果

- **Part 1**：两位 Reviewer 均完成单批调用，3/3 解析成功，非法引用为 0；Reconciliation 在本地执行。
- **Part 2**：3 条分歧中，`cluster-tunnel` 为 `evidence_interpretation`，需人工复核；另外两条可由确定性规则归类。
- **Part 3**：`cluster-absolute` 和 `cluster-v213` 最终为 `insufficient_evidence`；`cluster-tunnel` 保留 `manual_review`。

Reconciliation 不调用模型。原始 Fact A/B verdict、引用、理由和局限均保留；本地规则只处理结构化字段和已有审计信息，不用关键词猜测或模型裁决。

## 调用与验证基线

- Part 2/3 新增模型调用：`0`
- Part 2/3 新增网络请求：`0`
- Part 2/3 回归测试：`4 passed`
- 相关 Ruff、format check、`git diff --check`：通过

## 限制

Evidence 相关性和直接支持仍需人工区分。特别是 `evidence_interpretation` 分歧不会被本地规则强行裁决，必须保留人工复核。该 Pilot 不代表大规模真实模型准确率，也不改变四 Agent workflow 的调用次数。
