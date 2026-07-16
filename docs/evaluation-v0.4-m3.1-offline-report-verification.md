# v0.4 M3.1 Offline Report Verification Evaluation

## 1. M3.1 目标

M3.1 将已有 M1/M2 组件组合为离线 report-level orchestration：

```text
Markdown Report
  → Claim Extraction
  → ClaimRegistry
  → Evidence Adapter
  → EvidenceDecision
  → Fact Adapter
  → Offline report-verification artifact
```

本阶段验证完整的报告输入和证据决策准备流程，但不执行 Fact A/B reviewer。

## 2. Workflow 架构

`OfflineReportVerificationOrchestrator` 复用现有 deterministic Claim extractor、M2.1 Evidence Adapter 和 M2.2a Fact Adapter。Orchestrator 只负责顺序编排、阶段结果合并、Claim ID 校验和 artifact 生成。

未接入 `DualFactReviewCoordinator`，也未改变 EvidenceDecisionEngine、Claim schema 或既有 Dual Fact workflow。

## 3. 数据流

1. 读取 Markdown 报告并使用 basename 或显式 source name；
2. 通过 `DeterministicClaimExtractor` 生成 ClaimRegistry；
3. 使用离线 Retriever 执行 evidence retrieval 和 EvidenceDecision；
4. 将成功的 EvidenceDecisionBatch 转换为 FactReviewInput；
5. 合并成功结果与各阶段 failure slots；
6. 生成按 ClaimRegistry 顺序排列的 report verification artifact。

每个阶段都保留 Claim ID、顺序和失败信息，不对失败 Claim 自动 retry，也不生成空 FactReviewInput。

## 4. Artifact 输出

主 artifact 为 `report-verification.json`，包含：

- `metadata`：workflow、source file、source name 和 schema version；
- `claims`：ClaimExtractionResult 与 extraction metadata；
- `evidence`：RetrievalResult、EvidenceDecision 和 evidence failure；
- `fact_review`：当前为空的 Fact A/B 区域、call metadata 和 failure slots；
- `reconciliation`：所有 Claim 的 `not_reviewed` 状态及人工复核标记；
- `statistics`：Claim 数量、ready/failed 数量、模型/网络调用统计和 reconciliation execution 状态。

M3.1 不伪造 reviewer 或 reconciliation 结论。尚未进入 Fact review 的 Claim 使用 `not_reviewed`，并保留对应的 failure stage/code。

## 5. Claim ID Alignment

Claim ID 必须贯穿：

```text
ClaimExtraction
  = Evidence Retrieval
  = EvidenceDecision
  = FactReviewInput
  = report-verification artifact
```

Artifact 中的 evidence result 和 reconciliation record 按 ClaimRegistry 顺序排列。Retrieval、EvidenceDecision 或 FactReviewInput 的 Claim ID 不一致时，结果进入 failure slot，不进行静默覆盖。

## 6. Failure Slot Handling

当前保留的 failure 类型包括：

- retrieval failure；
- decision failure；
- Claim ID alignment failure；
- evidence source mismatch；
- invalid citation。

失败 Claim 会同时保留在 evidence failure slots 和最终 reconciliation record 中，并设置 `needs_manual_review=true`。失败不会被送入 reviewer，也不会被转换为空输入。

## 7. Zero Model/Network Cost

M3.1 离线流程不执行模型或网络调用：

- Claim extraction：0 model calls；
- Evidence Adapter：使用离线 Retriever；
- Fact Adapter：0 model calls；
- DualFactReviewCoordinator：未调用；
- evidence network requests：0。

artifact 和测试同时记录并验证 `model_call_count=0` 与 `network_request_count=0`。

## 8. 测试结果

新增 workflow tests 覆盖：

- offline end-to-end；
- artifact schema；
- Claim ID alignment；
- failure preservation；
- zero model/network cost；
- artifact 文件写出。

验证结果：

- `uv run pytest`：384 passed；
- `uv run ruff check .`：passed；
- `git diff --check`：passed。

## 9. 当前限制

- 未调用 `DualFactReviewCoordinator`；
- 未执行 Fact A/B reviewer；
- 未进行 Reconciliation execution；
- 未运行 live benchmark；
- 尚未提供 `verify-report` CLI；
- 尚未完成 full live report validation。

因此 M3.1 artifact 表示的是离线验证准备结果，不是最终事实核验结论。

## 10. M3.2 后续方向

M3.2 将在保持 Fact A/B 独立和预算约束的前提下接入现有 Dual Fact execution：

- 将 ready FactReviewInput 交给 Coordinator；
- 执行 Fact A/B batch reviewer calls；
- 记录 estimated/actual call metadata；
- 合并 Reconciliation 输出和 failure slots；
- 增加 report-level Dual Fact regression benchmark；
- 继续保持不重复 retrieval、不重复 EvidenceDecision 和零无意义 retry。
