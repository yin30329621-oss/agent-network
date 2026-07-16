# v0.4 M2.2b DualFactReviewCoordinator Integration Design

## 1. 目标和范围

M2.2b 将 M2.2a 产生的 `FactReviewInputAdapterBatchResult` 接入现有 `DualFactReviewCoordinator`。本阶段只增加编排和集成边界，不替换 v0.3.1 Dual Fact workflow，不修改 Fact A/B reviewer、Reconciliation 或 EvidenceDecisionEngine。

目标数据流：

```text
ClaimRegistry
  → Evidence Adapter
  → EvidenceDecision
  → Fact Adapter
  → FactReviewInputAdapterBatchResult
  → DualFactReviewCoordinator
  → Fact A / Fact B
  → Reconciliation
```

## 2. 当前 DualFactReviewCoordinator 架构

Coordinator 定义在 `src/agent_network/claim/fact_review.py`，输入是 `list[FactReviewInput]`，输出是按输入顺序排列的 `list[FactReconciliation]`。

当前流程：

1. 通过 `estimate()` 读取两个 reviewer 的 provider limits 和 `DualReviewBudget`；
2. 根据 Claim 数量、输入 token、evidence 字符数和预计输出 token 规划 batch；
3. 若无法满足预算或最大 batch 数，preflight 失败，不调用 reviewer；
4. 对每个 batch 分别 deep copy 为 Fact A 输入和 Fact B 输入；
5. 独立调用 `fact_a.review_batch()` 和 `fact_b.review_batch()`；
6. reviewer 异常被转换为 unavailable result；
7. 本地 `_reconcile()` 校验 citation、reviewer availability、canonical status 和 evidence gate；
8. 生成 `FactReconciliation`，包含 consensus、disagreement、manual review 等状态。

Fact A 和 Fact B 只能看到相同 Claim、EvidenceDecision、RetrievalResult 和 verification context，不能看到对方的输出。

## 3. Adapter Result → Coordinator 输入

M2.2b 只将 `FactReviewInputAdapterBatchResult.inputs` 交给 Coordinator：

```python
ready_inputs = adapter_result.inputs
estimate = coordinator.estimate(ready_inputs)
reconciliations = coordinator.review_batch(ready_inputs)
```

`failure_slots` 不转换为空的 `FactReviewInput`，也不进入 Fact A/B reviewer。编排层必须保留这些 Claim 的 `claim_id` 和 failure metadata，供最终报告或人工复核 routing 使用。

进入 Coordinator 前必须满足：

- `ready_count + failed_count == total_count`；
- 每个 ready input 的 Claim、retrieval、decision Claim ID 一致；
- 不存在空 decision、空 evidence placeholder 或伪造 citation；
- adapter 已完成 evidence consistency 校验；
- 失败 Claim 不进入 reviewer batch。

Coordinator 不重新调用 Retriever 或 `EvidenceDecisionEngine`，也不从 ClaimRegistry 重新构造证据上下文。

## 4. Failure slot 处理

失败按 Claim 保留，并在 reviewer routing 前分流：

| failure 类型 | 产生阶段 | Coordinator 行为 |
| --- | --- | --- |
| retrieval failure | Evidence Adapter | 不生成 ready input；不进入 Fact A/B；保留人工复核 slot |
| decision failure | EvidenceDecision Adapter | 不把 retrieval 升级为事实结论；不进入 reviewer；保留 decision failure 原因 |
| adapter failure | FactReviewInput Adapter | 不生成空 FactReviewInput；不调用 reviewer；保留 alignment/evidence/citation failure |

这些失败不触发自动 retry，不增加 retrieval、decision 或模型调用次数。后续 Reconciliation 汇总时，失败 Claim 应得到明确的 unavailable 或 manual review 状态，而不是被静默丢弃。

## 5. Fact A/B isolation

`FactReviewInput` 是 frozen dataclass，但内部 `claim`、`decision` 和 `retrieval` dict 及其 nested list/dict 仍然可变。Coordinator 必须在每个 batch 调用 reviewer 前分别 deep copy：

```python
a_inputs = [deepcopy(item.for_fact_a()) for item in input_batch]
b_inputs = [deepcopy(item.for_fact_b()) for item in input_batch]
```

隔离规则：

- Fact A 不读取 Fact B result；
- Fact B 不读取 Fact A result；
- 两个 reviewer 不共享任何 mutable nested object；
- reviewer 对输入的修改不得回写 adapter result 或另一 reviewer 输入；
- Reconciliation 只能读取各自 reviewer 输出和共同的原始 evidence context。

必须增加 isolation test：在 Fact A handler 中修改 nested evidence、Claim 或 retrieval 字段，验证 Fact B 收到的 payload 和原始 adapter result 均未改变。

## 6. Budget contract

M2.2b 沿用现有 `DualReviewBudget`，不新增按 Claim 的模型调用。预算流程为：

1. 先过滤 failure slots，只对 ready inputs 调用 `estimate()`；
2. estimate 计算 Fact A calls、Fact B calls、total calls、batch sizes 和 estimated tokens；
3. preflight 校验 `max_batches`、输入 token、evidence 字符数、预计输出 token、provider max tokens 和 `max_estimated_tokens`；
4. preflight 通过后才允许 reviewer 调用；
5. 按计划 batch 分别调用 Fact A 和 Fact B；
6. Benchmark 记录实际 reviewer/model calls，并与 estimate 对比。

预算超限时：

- 抛出明确的 budget exceeded 结果或异常；
- 不调用 Fact A/B；
- 不自动扩大 max tokens；
- 不自动增加 batch 或 retry；
- 不重新进行 retrieval/decision。

成本统计责任分层：Adapter 记录输入和失败统计，Coordinator 负责 reviewer call estimate，Benchmark 负责实际模型调用、网络请求和 runtime。

## 7. v0.3.1 baseline compatibility

M2.2b 必须保持 v0.3.1 的可复现基线：

- Fact A/B 保持独立调用；
- 现有 dual review batch 结构不变；
- baseline live validation 为 8 model calls；
- evidence retrieval network requests 保持 0；
- 不增加 agent、reviewer 或额外 LLM call；
- 本地 Reconciliation 的状态和 evidence gating 规则保持兼容。

M2.2b 的 adapter 只改变 FactReviewInput 的来源，不改变 Coordinator 的 reviewer prompt、provider 配置、batch budget 或 reconciliation contract。

## 8. 测试计划

### Integration test

使用离线 `FactReviewInputAdapterBatchResult` fixture，验证 ready inputs 能进入 Coordinator，并生成与 Claim ID 对齐的 Reconciliation；failure slots 不进入 reviewer。

### Isolation test

使用可记录并修改输入的 fake reviewer，验证 Fact A/B deep copy、nested object 隔离、输出互不可见和 adapter result 不被污染。

### Budget and call count test

验证 estimate/preflight 在超预算时阻止 reviewer 调用，并验证正常 batch 的 estimated calls 与实际 reviewer calls 一致。

### Regression benchmark

运行现有 v0.3.1 Dual Fact benchmark，确认：

- Fact A/B 仍独立；
- baseline 仍为 8 model calls；
- evidence network requests 仍为 0；
- Claim ID 和 reconciliation status 分布保持兼容；
- 既有 fixtures 和 API 继续解析。

## 9. M2.2b 不实现的内容

本阶段不新增 Retriever、EvidenceDecisionEngine、Fact reviewer、Reconciliation engine 或 report CLI；不进行 live benchmark 调参，不改变 v0.3.1 workflow，不为失败 Claim 增加额外模型调用。
