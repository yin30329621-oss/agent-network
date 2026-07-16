# v0.4 M3.2 Report-level Dual Fact Execution Evaluation

## 1. M3.2 目标

M3.2 在 M3.1 离线 report workflow 基础上，增加可选的 report-level Dual Fact execution：

```text
Report
  → Claim Extraction
  → EvidenceDecision
  → FactReviewInput
  → DualFactReviewCoordinator
  → Fact A / Fact B
  → Reconciliation
  → report-verification artifact
```

Dual Fact 通过 `enable_dual_fact` 控制，默认关闭，以保持 M3.1 行为兼容。

## 2. M3.1 → M3.2 演进

M3.1 只完成 Claim extraction、离线 EvidenceDecision、FactReviewInput 准备和 offline artifact 输出，不调用 reviewer。

M3.2 复用 M3.1 的 ready FactReviewInput，接入现有 `DualFactReviewCoordinator`，执行 Fact A/B batch reviewer，并将本地 Reconciliation 结果写入 report-level artifact。

本阶段未修改 Claim schema、EvidenceDecisionEngine、Coordinator 核心逻辑或 Reconciliation 规则。

## 3. Report-level Dual Fact workflow

`OfflineReportVerificationOrchestrator` 的默认路径仍为 M3.1。启用 `enable_dual_fact=True` 且提供现有 Coordinator 后，执行：

1. 提取 Markdown Claim 并构建 ClaimRegistry；
2. 运行 Evidence Adapter 和 EvidenceDecision；
3. 运行 Fact Adapter，过滤失败 Claim；
4. 对 ready FactReviewInput 执行 Coordinator budget preflight；
5. 批量独立调用 Fact A 和 Fact B；
6. 接收 `FactReconciliation`；
7. 合并成功结果与 failure slots；
8. 输出包含 reviewer 和 Reconciliation 的 artifact。

未启用开关时，不调用 Coordinator 或任何 reviewer。

## 4. Fact A/B isolation

M3.2 保持现有隔离 contract：

- Fact A/B 输入分别 deep copy；
- 不共享 mutable nested object；
- Fact A 不读取 Fact B 输出，Fact B 不读取 Fact A 输出；
- reviewer 修改不会污染另一方输入或原始 FactReviewInput；
- Reconciliation 只消费各自 reviewer 输出和共同 evidence context。

新增测试验证 Fact A 修改 nested evidence 后，Fact B 输入和原始 adapter result 保持不变。

## 5. Reconciliation artifact

启用 Dual Fact 后，`fact_review` artifact 包含：

- `fact_a` reviewer results；
- `fact_b` reviewer results；
- estimated/actual reviewer call metadata；
- reviewer 和 coordinator failure slots。

`reconciliation` 按 Claim ID 保留所有 Claim，记录 status 和 `needs_manual_review`。没有进入 reviewer 的失败 Claim 仍保留 `not_reviewed` 或对应失败信息，不会被静默丢弃。

## 6. Failure routing

失败 Claim 不进入 Fact A/B reviewer：

- retrieval failure：保留 retrieval failure slot；
- decision failure：不升级为事实结论；
- Fact Adapter alignment/evidence failure：不生成空 FactReviewInput；
- Coordinator failure：保留 coordinator failure slot；
- Claim ID 不一致：进入 alignment failure，不覆盖原始 Claim ID。

failure routing 不触发重复 retrieval、EvidenceDecision 或自动 retry。

## 7. Budget / Call Metadata

M3.2 复用现有 Coordinator 的 budget preflight 和 batch planning：

- 只对 ready Claim 估算 reviewer calls；
- 超预算时不调用 Fact A/B；
- Fact A/B 按 batch 调用，不按 Claim 单独调用；
- adapter 记录输入/失败统计；
- Coordinator adapter 记录 estimated/actual reviewer calls；
- evidence network requests 保持来自离线 Retriever 的零计数。

## 8. 测试结果

新增测试覆盖：

- Dual Fact workflow；
- Fact A/B isolation；
- Reconciliation artifact；
- failure routing；
- Claim ID consistency；
- call metadata。

验证结果：

- `uv run pytest`：387 passed；
- `uv run ruff check .`：passed；
- `git diff --check`：passed。

## 9. 当前限制

- 尚未完成 `verify-report` CLI；
- 尚未完成 live validation；
- 当前 report-level execution 仍通过编程 API 触发；
- 尚未生成面向生产报告的完整离线/live benchmark 报告。

后续应在保持 Fact A/B 独立、batch budget 和 failure 可追踪的前提下，实现 M3.3 CLI 与 live validation。
