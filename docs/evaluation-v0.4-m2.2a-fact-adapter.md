# v0.4 M2.2a FactReviewInput Adapter Evaluation

## 1. 背景和目标

M2.1 已完成离线 ClaimRegistry → RetrievalResult → EvidenceDecision adapter。M2.2a 在不改变 v0.3.1 Dual Fact workflow 的前提下，将已经完成的 `EvidenceDecisionBatch` 转换为可供后续 Fact review 使用的 `FactReviewInput`。

本阶段只消费既有 EvidenceDecision 结果，不重新检索、不重新执行 EvidenceDecisionEngine，也不接入 Dual Fact reviewer。

## 2. EvidenceDecision → FactReviewInput 架构

```text
EvidenceDecisionBatch
    ├── completed review inputs
    └── decisions / retrieval context
            ↓
FactReviewInputAdapter
            ↓
FactReviewInputAdapterBatchResult
    ├── ready FactReviewInput list
    └── failure slots
```

Adapter 位于 `agent_network.claim.fact_adapter`，复用现有 `FactReviewInput` contract。它只负责转换、校验和统计，不调用 Retriever、`EvidenceDecisionEngine` 或任何 reviewer。

## 3. Adapter contract

输出类型为 `FactReviewInputAdapterBatchResult`，包含：

- `inputs`：成功生成且可安全交给后续 Coordinator 的 `FactReviewInput` 列表；
- `failure_slots`：按 Claim 记录的结构化 `AdapterFailure`；
- `claim_ids`：输入 batch 的 Claim ID 顺序；
- `total_count`、`ready_count`、`failed_count`；
- `cost_metadata`：上游成本计数和本 adapter 的零调用计数；
- `results`：逐 Claim 的 ready/failure slot 结果。

失败 Claim 保留 failure slot，但不会生成空的或缺少 evidence/decision 的 `FactReviewInput`。正常情况下满足：

```text
ready_count + failed_count = total_count
```

## 4. Claim ID alignment

Adapter 校验以下 ID 链路：

```text
EvidenceDecision.claim_id
    = FactReviewInput.claim["claim_id"]
    = FactReviewInput.decision["claim_id"]
    = FactReviewInput.retrieval["claim_id"]
```

缺失、错配、重复 decision Claim ID 会生成 alignment failure。Adapter 不生成新的 Claim ID，也不使用 reviewer 输出覆盖原始 Claim ID。

## 5. Evidence/citation consistency

Adapter 保留既有 decision 和 retrieval 中的 evidence context，不修改 `EvidenceDecision.status`、evidence、rule audit 或 limitations。

同时执行以下约束：

- decision evidence 的 `chunk_id` 必须存在于对应 retrieval results；
- 如果输入包含 `cited_chunk_ids`，每个 citation 必须属于 decision evidence；
- 不一致的 evidence 来源进入 failure slot；
- 不生成不存在的 chunk ID、URL 或 citation。

## 6. Failure slot design

失败按 Claim 保留，并区分主要原因：

- `decision_claim_id_missing`：没有匹配的 EvidenceDecision；
- `decision_claim_id_mismatch`：decision Claim ID 与输入不一致；
- `duplicate_decision_claim_id`：同一 Claim 存在多个 decision；
- `evidence_source_mismatch`：decision evidence 不属于 retrieval results；
- `invalid_citation`：citation 不属于 decision evidence；
- `retrieval_claim_id_mismatch`：retrieval context 的 Claim ID 不一致。

失败不会被转换为成功输入，也不会触发自动 retry。后续由 M2.2b 决定如何将 failure slot 路由到人工复核或 unavailable 状态。

## 7. Cost metadata

M2.2a 的成本边界是零新增调用：

- adapter model calls：`0`；
- adapter network requests：`0`；
- 上游 `EvidenceDecisionBatch` 的 model/network 计数原样记录；
- 不调用 Retriever；
- 不调用 EvidenceDecisionEngine；
- 不调用 Fact A/B。

因此 M2.2a 不会重复 retrieval 或 evidence decision，也不会改变现有 benchmark 的模型调用次数。

## 8. 测试结果

新增 `tests/test_fact_adapter.py`，覆盖：

- success conversion；
- Claim ID 对齐；
- misaligned decision failure；
- failure slot 保留；
- evidence chunk 和 citation 保留/校验；
- empty input；
- model/network count 为零。

验证结果：

- `uv run pytest`：375 passed；
- `uv run ruff check .`：passed；
- `git diff --check`：passed。

## 9. 当前限制

M2.2a 仍是离线转换 prototype：

- 未接入 `DualFactReviewCoordinator`；
- 未调用 Fact A/B reviewer；
- 未进行 Reconciliation；
- 未进行 report-level validation；
- 未改变现有 Dual Fact workflow、batch budget 或 live benchmark。

## 10. M2.2b 后续方向

M2.2b 将把 ready `FactReviewInput` 接入现有 `DualFactReviewCoordinator`，并继续保持 Fact A/B 独立。后续工作包括：

- 传递和预估 `DualReviewBudget`；
- Fact A/B deep-copy isolation 验证；
- reviewer result Claim ID 校验；
- unavailable reviewer 与 failure routing；
- citation validation 与本地 Reconciliation；
- v0.3.1 regression benchmark。

这些工作不属于 M2.2a 的实现范围。
