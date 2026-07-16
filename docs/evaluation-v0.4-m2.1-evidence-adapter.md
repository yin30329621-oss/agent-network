# v0.4 M2.1 Evidence Adapter Evaluation

## 1. 背景和目标

v0.4 M1 已建立 Markdown Report → Claim Extraction → ClaimRegistry 入口。M2.1 在不替换 v0.3.1 验证流程的前提下，增加离线的 ClaimRegistry → EvidenceDecision adapter prototype，为后续 report-level verification 提供稳定边界。

本阶段只负责把已有 ClaimRegistry 编排为逐 Claim 的检索与证据决策结果，不接入 Fact A/B、Dual Fact 或 Reconciliation。

## 2. Adapter 架构

Adapter 位于 `agent_network.claim` 模块，复用现有离线 evidence retriever 和 `EvidenceDecisionEngine`：

```text
ClaimRegistry
    → RetrievalResult
    → EvidenceDecision
    → ClaimEvidenceAdapterResult
    → ClaimEvidenceAdapterBatchResult
```

Adapter 负责 request/config、批量编排、结果顺序和失败槽位管理。核心 Claim schema、检索器、EvidenceDecisionEngine 和既有 Verification Pipeline 均保持不变。

## 3. 输入输出 contract

输入是现有 `ClaimRegistry` 及 adapter request/config。输出是按 registry 顺序排列的 `ClaimEvidenceAdapterBatchResult`，每个结果保留对应 `claim_id`，并携带检索结果、证据决策或结构化失败信息。

失败使用 `AdapterFailure` 表示，并区分 retrieval failure 与 decision failure。空 registry 返回空 batch result，不触发任何下游调用。

## 4. Claim ID 对齐设计

每个输入 Claim 生成一个结果槽位，结果中的 `claim_id` 必须与输入完全一致。Adapter 不重新生成、重排或合并 Claim ID；即使单个 Claim 检索或决策失败，也保留该 Claim 的 failure slot。因此调用方可以通过 Claim ID 可靠地对齐原始 Claim、证据和决策结果。

## 5. Failure handling

Adapter 对每个 Claim 独立记录阶段结果：

- retrieval failure：无法取得该 Claim 的 `RetrievalResult`；
- decision failure：检索完成，但证据决策阶段失败；
- success：同时包含检索结果和 `EvidenceDecision`。

失败不会被静默转换为成功，也不会用不存在的证据或 citation 自动补全。批处理继续保留其他 Claim 的结果，最终 batch result 同时提供成功结果和失败槽位，便于后续人工诊断与重试策略设计。

## 6. 零模型、零网络约束

M2.1 使用离线 evidence 数据和现有确定性组件，不调用模型、不发起网络请求，也不接入 Fact A/B。测试明确验证 `model_call_count=0` 和 `network_request_count=0`，以确保该 prototype 不改变现有成本边界。

## 7. 测试结果

- `pytest`: 370 passed
- `ruff`: passed
- `git diff --check`: passed

覆盖范围包括 Claim ID 对齐、registry 顺序、failure slot、空 registry、Fact A/B 不调用，以及零模型/零网络约束。

## 8. 当前限制

M2.1 仍是离线 adapter prototype：

- 未接入 Fact A/B；
- 未接入 Dual Fact Coordinator 或 Reconciliation；
- 未进行 report-level validation；
- 尚未提供面向生产报告的端到端 CLI 编排和结果持久化；
- 证据检索与决策结果尚未形成完整的跨报告 benchmark。

## 9. M2.2 后续方向

M2.2 可在保持 Fact A/B 独立和调用预算不变的前提下，设计 ClaimEvidenceAdapterBatchResult 到 `FactReviewInput` 的显式 adapter，并补充：

- report-level ClaimRegistry 到 FactReviewInput 的编排；
- evidence context、citation 和 `claim_id` 的一致性校验；
- Fact A/B 输入隔离测试；
- Dual Fact 与本地 Reconciliation 的集成验证；
- 离线 fixture 驱动的 report-level benchmark。

这些工作应作为后续 milestone 评估，不属于 M2.1 的实现范围。
