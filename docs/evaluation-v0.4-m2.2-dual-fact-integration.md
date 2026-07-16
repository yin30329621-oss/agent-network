# v0.4 M2.2 Dual Fact Integration Evaluation

## 1. M2.2 目标

M2.2 将 v0.4 M2.1 产生的 EvidenceDecision 结果安全接入现有 v0.3.1 Dual Fact workflow：

```text
ClaimRegistry
  → Evidence Adapter
  → EvidenceDecision
  → Fact Adapter
  → FactReviewInput
  → DualFactReviewCoordinator
  → Fact A / Fact B
  → Reconciliation
```

本阶段采用 adapter 和 orchestration 方式，不替换现有 reviewer、Coordinator 或 Reconciliation 规则。

## 2. M2.2a / M2.2b 架构

### M2.2a

`fact_adapter.py` 消费已经完成的 `EvidenceDecisionBatch`，生成 `FactReviewInputAdapterBatchResult`。输出包含 ready `FactReviewInput`、failure slots、Claim ID 顺序、数量统计和成本 metadata。

M2.2a 不调用 Retriever 或 `EvidenceDecisionEngine`。

### M2.2b

`fact_coordinator_adapter.py` 只将 ready inputs 传递给现有 `DualFactReviewCoordinator`，接收 Fact A/B reviewer 执行结果和本地 Reconciliation 输出，同时保留 M2.2a failure slots。

M2.2b 不重复 retrieval 或 evidence decision，也不修改 Fact A/B reviewer 核心逻辑。

## 3. EvidenceDecision → FactReviewInput

Fact Adapter 对每个 Claim 校验：

- EvidenceDecision、FactReviewInput decision 和 retrieval 的 `claim_id` 一致；
- decision evidence 来源于对应 retrieval results；
- citation 只能引用 decision evidence 中已有的 chunk ID；
- adapter 不修改 EvidenceDecision status、evidence、rule audit 或 limitations。

失败 Claim 保留结构化 failure slot，不生成空的或缺少 evidence/decision 的 FactReviewInput。

## 4. FactReviewInput → DualFactReviewCoordinator

Coordinator Adapter 只消费 `FactReviewInputAdapterBatchResult.inputs`：

1. 过滤 failure slots；
2. 对 ready inputs 执行 Coordinator estimate；
3. 通过预算 preflight 后调用现有 `review_batch()`；
4. 接收 Fact A/B batch reviewer 结果；
5. 保持输入顺序和 Claim ID 对齐；
6. 返回 Reconciliation 结果及失败槽位。

失败 Claim 不会进入 Fact A/B reviewer，也不会被转换为空输入。

## 5. Fact A/B isolation

Coordinator 延续现有隔离策略：

- Fact A 和 Fact B 分别接收独立 deep copy；
- 不共享 mutable nested object；
- 不共享 reviewer 输出；
- reviewer 对输入的修改不会污染另一 reviewer 或原始 adapter result；
- Reconciliation 只读取两个 reviewer 的输出和共同 evidence context。

测试已验证 Fact A 修改 nested evidence 后，Fact B 输入和原始 FactReviewInput 保持不变。

## 6. Failure slot routing

当前支持以下 failure routing：

- retrieval failure：不生成 ready input，不进入 reviewer；
- decision failure：不把 retrieval 结果升级为事实结论；
- adapter/alignment failure：保留 Claim ID、stage、code 和安全消息；
- coordinator failure：ready Claim 转为 coordinator failure slot；
- reconciliation alignment failure：不接受 Claim ID 错配的 reconciliation。

failure slots 不触发自动 retry，不增加 retrieval、decision 或 reviewer 调用。

## 7. Budget preflight

M2.2b 复用现有 `DualReviewBudget` 和 Coordinator `estimate()`：

- 先估算 Fact A/B batch 数和 reviewer calls；
- 校验输入 token、evidence 字符数、预计输出 token、provider max tokens 和 max batches；
- 超预算时在 reviewer 调用前失败；
- 不自动增加 max tokens、batch 或 retry。

## 8. Call metadata

成本统计按层负责：

- Fact Adapter：输入数量、failure 数量和 adapter 零调用 metadata；
- Coordinator Adapter：estimated reviewer calls、actual reviewer calls 和 failure routing；
- Benchmark：最终实际模型调用、网络请求和 runtime。

本阶段不增加 Retriever、EvidenceDecisionEngine 或 evidence network request。

## 9. Regression benchmark 结果

现有 Dual Fact benchmark regression tests 已通过，验证：

- Fact A/B 输入保持独立；
- batch 调用结构保持兼容；
- Claim ID 和 Reconciliation 输出保持对齐；
- v0.3.1 既有 benchmark fixture 未修改；
- baseline 成本约束保持：8 model calls、0 evidence network requests。

全量验证结果：

- `uv run pytest`：380 passed；
- `uv run ruff check .`：passed；
- `git diff --check`：passed。

## 10. 当前限制

- 尚未完成 report-level CLI integration；
- 尚未完成 full live report validation；
- 当前集成主要由离线 fixture 和现有 regression benchmark 验证；
- failure slots 到最终人工复核系统的持久化和 UI routing 尚未实现。

后续可在保持 Fact A/B 独立、8-call budget 和零 evidence network request 约束的前提下，继续实现 report-level orchestration 和 live validation。
