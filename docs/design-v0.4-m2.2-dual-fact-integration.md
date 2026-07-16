# v0.4 M2.2 Dual Fact Integration Design

## 1. 目标

M2.2 将 M2.1 产生的 `ClaimEvidenceAdapterBatchResult` 安全接入现有 `FactReviewInput` 和 `DualFactReviewCoordinator`。本 milestone 增加 adapter 与编排层，不替换 v0.3.1 Dual Fact workflow，不改变 Fact A/B 的独立运行方式。

目标数据流为：

```text
ClaimRegistry
  → Evidence Adapter
  → RetrievalResult + EvidenceDecision
  → FactReviewInput
  → DualFactReviewCoordinator
  → Fact A / Fact B
  → Reconciliation
```

## 2. 当前实现基线

`FactReviewInput` 定义在 `src/agent_network/claim/evidence_decision.py`，是 frozen、slots dataclass，当前字段为：

- `claim: dict[str, Any]`
- `decision: dict[str, Any]`
- `retrieval: dict[str, Any]`

它通过 `to_dict()`、`for_fact_a()` 和 `for_fact_b()` 暴露相同的逻辑输入。字段内容分别来自 Claim、EvidenceDecision 和 RetrievalResult 的序列化结果。

`DualFactReviewCoordinator` 定义在 `src/agent_network/claim/fact_review.py`。当前调用流程是：先用 `estimate()` 根据 reviewer provider limits 和 `DualReviewBudget` 规划 batch；再按输入、输入 token、证据字符数和预期输出预算拆分 batch；每个 batch 分别 deep copy 为 Fact A/B 输入；独立调用两个 reviewer；最后按输入顺序调用本地 `_reconcile()`。

Coordinator 已维护 `model_call_count` 和 `network_request_count` 字段，并通过 `DualReviewBudget` 传递 batch size、输入/输出 token、证据字符数、最大 batch 数和安全比例约束。

## 3. EvidenceDecision → FactReviewInput adapter

M2.2 建议新增独立的 orchestration/adapter 函数或小型类，输入为 M2.1 的 batch result，输出为 `list[FactReviewInput]` 及逐 Claim failure metadata。它不重新检索、不重新执行 EvidenceDecisionEngine，也不修改三类既有 schema。

对每个成功的 adapter result：

1. 读取 `claim_id` 对齐的 `retrieval` 和 `decision`；
2. 调用现有对象的 `to_dict()` 生成普通数据快照；
3. 从 registry 或 adapter 上下文取得对应 Claim 的 `to_dict()`；
4. 验证三处 `claim_id` 一致后构造 `FactReviewInput`。

输出的 FactReviewInput 只包含已经完成的检索和证据决策上下文。Adapter 不允许覆盖 `EvidenceDecision.status`、证据列表、citation 或 limitation；如需附加编排信息，应放在 adapter 外部的 failure/report metadata 中。

### 3.1 Adapter Result contract

M2.2 adapter 的显式输出 contract 为 `FactReviewInputAdapterBatchResult`，不直接返回一个可能丢失失败信息的 `list[FactReviewInput]`。建议字段为：

- `inputs: list[FactReviewInput]`：仅包含成功完成且可安全交给 Coordinator 的输入；
- `failure_slots: list[AdapterFailure]`：按原始 Claim 顺序记录无法生成输入的 Claim；
- `claim_ids: list[str]`：覆盖本次输入 registry 的完整 Claim ID 顺序；
- `total_count: int`：输入 Claim 总数；
- `ready_count: int`：成功生成 FactReviewInput 的数量；
- `failed_count: int`：failure slot 数量；
- `cost_metadata: dict[str, int | bool]`：输入统计、失败统计及 adapter 阶段的模型/网络调用计数。

`ready_count + failed_count` 必须等于 `total_count`。失败 Claim 必须保留 failure slot，但不得生成空的、伪造 evidence 或缺少 decision 的 `FactReviewInput`。只有 `ready` 输入才能进入 `DualFactReviewCoordinator`；失败 Claim 由后续 routing 生成明确的人工复核或 unavailable 状态。

### 3.2 Reviewer result alignment

Coordinator 在 Reconciliation 前必须校验每个 reviewer result 的 `claim_id` 与对应输入的 `claim_id` 完全一致。缺失、错误或无法解析的 reviewer Claim ID 不得按 batch index 静默接受，应标记为 `invalid/misaligned reviewer result`，并进入人工复核路径。Reconciliation 的主 Claim ID 始终来自 `FactReviewInput`，不能由 reviewer 输出覆盖。

### 3.3 Evidence consistency rules

进入 reviewer 前和 Reconciliation 前都必须保持以下不变量：

- Claim、RetrievalResult、EvidenceDecision 和 FactReviewInput 的 `claim_id` 一致；
- FactReviewInput 中的 evidence 必须来自同一 Claim 对应的 RetrievalResult；
- reviewer citation 只能引用对应 EvidenceDecision.evidence 中已有的 `chunk_id`；
- adapter 只能序列化和校验 EvidenceDecision，不得修改其 `status`、evidence、rule audit 或 limitations；
- 不一致的 evidence context 或 citation 必须失败并升级人工复核，不能降级为普通成功结果。
## 4. Fact A/B 隔离策略

`FactReviewInput` 的 dataclass 外壳不可变，但内部三个 dict 及其 nested list/dict 仍然是可变对象。因此 adapter 应在构造时生成独立序列化快照，Coordinator 在调用 reviewer 前继续分别执行：

```python
a_inputs = [deepcopy(item.for_fact_a()) for item in input_batch]
b_inputs = [deepcopy(item.for_fact_b()) for item in input_batch]
```

不得向 Fact A 传递 Fact B 的结果，也不得让两个 reviewer 共享同一 nested object。任何 reviewer 对输入的修改都必须限制在自己的 deep copy 内；Reconciliation 只能读取两个 reviewer 的输出与共同的原始 evidence context。

必须保留现有 Fact A/B 独立 batch 调用和调用顺序。Isolation adapter 不应缓存 reviewer 输出，也不应把一方的 status、reasoning 或 citation 写回另一方输入。

## 5. Batch budget 传递

M2.2 adapter 不创建新的模型调用预算。它只负责把已完成的 evidence batch 转换为 FactReviewInput，并将调用方提供的 `DualReviewBudget` 原样传给 `DualFactReviewCoordinator`。

预算边界由 Coordinator 统一执行：

- `claims_per_batch` / `max_claims_per_batch`；
- `max_batches`；
- reviewer 的 `max_tokens` 与 timeout；
- `max_input_tokens_per_batch`；
- `max_expected_output_tokens_per_batch`；
- `max_evidence_chars_per_batch`；
- `max_estimated_tokens` 和 output safety ratio。

Adapter 不按 Claim 追加调用，不重复 retrieval/decision，也不为了失败 Claim 自动 retry。运行前仍先调用 `estimate()`，预算超限时在 reviewer 调用前失败。

成本统计责任必须分层：

- Adapter 负责输入数量、ready/failed 数量、failure slot 和自身阶段的模型/网络调用统计；
- Coordinator 负责根据 `DualReviewBudget` 估算 Fact A/B reviewer batch 数和 estimated reviewer calls；
- Benchmark 负责记录实际 reviewer/model calls、实际网络请求和最终 runtime。

M2.2 adapter 不允许调用 Retriever 或 `EvidenceDecisionEngine`，也不接受会触发这些调用的 lazy provider。它只能消费 M2.1 已完成的 `ClaimEvidenceAdapterBatchResult`；因此 adapter 本身不会造成重复 retrieval 或重复 evidence decision。
## 6. Claim ID 贯穿规则

`claim_id` 是唯一的跨层关联键：

```text
Claim.claim_id
  = RetrievalResult.claim_id
  = EvidenceDecision.claim_id
  = FactReviewInput.claim["claim_id"]
  = FactReconciliation.claim_id
```

Adapter 必须按 ClaimRegistry 顺序产生输入，并拒绝以下情况：retrieval 的 Claim ID 不匹配、decision 缺少对应 Claim ID、重复或缺失的 decision slot。Coordinator 的 reconciliation 结果必须使用 FactReviewInput 的 Claim ID，而不是使用 reviewer 返回正文中的任意标识覆盖它。

## 7. Failure handling

失败应保持逐 Claim、可审计且不伪造成功：

| 阶段 | 表示 | 后续行为 |
| --- | --- | --- |
| retrieval failure | `AdapterFailure(stage="retrieval")` | 不生成可供 reviewer 使用的 evidence；保留 Claim failure slot，路由人工复核或后续显式重试 |
| decision failure | `AdapterFailure(stage="decision")` | 不把检索结果升级为事实结论；该 Claim 不进入正常 Fact review，或以明确 unavailable context 进入人工复核 |
| unavailable reviewer | Coordinator 的 `None`/failed reviewer result | 生成 `single_reviewer_available` 或 `both_reviewers_unavailable`，设置 manual review metadata |
| invalid citation | Reconciliation 校验 cited chunk ID 不在 decision evidence 集合中 | 标记 `INVALID_CITATION`，过滤无效 citation，并升级人工复核 |

Failure metadata 必须保留原始 `claim_id`、stage、safe code 和安全消息，不保存或生成不存在的 chunk ID、URL 或 evidence。失败不能触发重复 retrieval/decision，也不能增加 Fact A/B 调用次数。

## 8. 测试计划

M2.2 实现前后应新增以下覆盖，并保留既有 M2.1 与 v0.3.1 测试：

- isolation test：Fact A/B 收到结构相同但互不共享的 deep-copied nested input，修改一方不会影响另一方；
- claim alignment test：从 Claim 到 reconciliation 的 Claim ID 全链路一致，缺失/错配 slot 会失败；
- call count test：adapter 接入不重复 retrieval/decision，Fact A/B 仍按 batch 调用，模型调用估算和实际调用数符合预算；
- failure routing test：四类 failure 均得到明确的 failure/reconciliation 状态和人工复核原因；
- citation test：只允许引用同一 EvidenceDecision 中的已有 chunk ID；
- regression benchmark：现有 v0.3.1 Dual Fact benchmark 的输入、Fact A/B 独立性、调用次数和 reconciliation 输出保持兼容。

## 9. M2.2 拆分

M2.2 分为两个实现子阶段：

- **M2.2a adapter**：实现 `FactReviewInputAdapterBatchResult`、Claim ID 对齐、failure slots、evidence consistency 校验、成本 metadata 和 Fact A/B 输入 deep-copy isolation；不调用 Retriever、`EvidenceDecisionEngine` 或 Fact reviewer。
- **M2.2b coordinator integration**：将 ready inputs 接入现有 `DualFactReviewCoordinator`，传递 `DualReviewBudget`，增加 reviewer result Claim ID 校验、unavailable routing、citation 校验和 v0.3.1 regression benchmark。

只有 M2.2a 的 contract 和隔离测试稳定后，才进入 M2.2b；两个阶段都不得改变现有 Fact A/B workflow 或增加额外模型调用。
## 10. 兼容性与范围

M2.2 只新增 ClaimEvidenceAdapterBatchResult 到 FactReviewInput 的编排边界，不修改 Claim schema、RetrievalResult、EvidenceDecision、FactReviewInput、Fact A/B prompt 或 Reconciliation contract。现有直接构造 `FactReviewInput` 的调用方仍应继续工作。

不在本 milestone 内新增 agent、模型 provider、网络 evidence source、重复缓存层或 report CLI 入口。完成标准是离线 adapter 能安全供给现有 Coordinator，并证明隔离、Claim ID 对齐、预算和 v0.3.1 regression 均成立。
