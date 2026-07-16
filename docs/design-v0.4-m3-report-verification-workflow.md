# v0.4 M3 Report-level Verification Workflow Design

## 1. M3 目标

M3 将 v0.4 M1/M2 已完成的能力组合为一个 report-level verification 入口：

```text
Markdown Report
  → Claim Extraction
  → ClaimRegistry
  → Evidence Adapter
  → EvidenceDecision
  → Fact Adapter
  → Dual Fact Review
  → Reconciliation
```

M3 只增加 orchestration layer 和 CLI 入口，不改变已有 Claim、EvidenceDecision、Dual Fact 或 Reconciliation contract。

## 2. 当前 CLI 能力

当前 CLI 已支持：

```bash
agent-network extract-claims report.md
```

该命令读取 Markdown，调用现有 deterministic claim extractor，并输出 `ClaimExtractionResult` JSON，包含 Claim 元数据和 extraction statistics。

M3 应复用这一入口的文件读取、`source_name`、稳定 Claim ID 和 extraction failure 表达，不复制 Claim extraction 逻辑。

## 3. 当前 workflow 基线

现有 review pipeline 已具备以下独立边界：

- ClaimRegistry → Evidence Adapter：离线 retrieval 和确定性 EvidenceDecision；
- EvidenceDecision → Fact Adapter：生成 ready `FactReviewInput` 和 failure slots；
- FactReviewInput → DualFactReviewCoordinator：批量、独立执行 Fact A/B；
- Coordinator → Reconciliation：本地确定性汇总、citation 校验和人工复核 routing。

M3 orchestration 只负责连接这些已存在的边界，不把各模块的职责重新实现到 CLI 中。

## 4. Report-level orchestration layer

建议新增独立的 report verification service/module，例如：

```text
ReportVerificationOrchestrator
  1. read report
  2. extract claims
  3. build ClaimRegistry
  4. run Evidence Adapter
  5. run Fact Adapter
  6. run Coordinator Adapter
  7. merge ready reconciliations and failure slots
  8. write output artifacts
```

Orchestrator 应接受显式 config，包括 source name、evidence cache、document filters、top-k、offline/network policy、DualReviewBudget、output directory 和 verification mode。

每个阶段都必须保留 `claim_id`、顺序、统计和 failure metadata。失败 Claim 不得被静默丢弃，也不得生成空 FactReviewInput。

## 5. `verify-report` CLI 设计

建议新增命令：

```bash
agent-network verify-report report.md \
  --output-dir artifacts/report-name \
  --source-name report-name \
  --offline \
  --confirm-live-model-calls \
  --confirm-planned-call-count 8
```

建议选项：

- `report.md`：输入 Markdown 报告；
- `--output-dir`：artifact 输出目录；
- `--source-name`：覆盖默认 basename；
- `--offline`：只使用已有 evidence cache；
- `--top-k`：Evidence retrieval 限制；
- `--max-claims-per-batch`：Fact review batch 限制；
- `--confirm-live-model-calls`：显式允许真实 reviewer 调用；
- `--confirm-planned-call-count`：确认预估模型调用次数；
- `--dry-run`：只执行 extraction、planning 和成本估算。

CLI 不应直接调用 provider、Retriever 或 reviewer；所有执行应通过 orchestrator 和既有 adapter。

## 6. Output artifact schema

建议每次运行生成一个版本化的 `report-verification.json`，顶层结构如下：

```json
{
  "schema_version": "v0.4-m3",
  "run_id": "...",
  "source_file": "report.md",
  "source_name": "report",
  "status": "completed",
  "claims": [],
  "extraction": {},
  "evidence": {},
  "fact_review": {},
  "reconciliation": {},
  "failure_slots": [],
  "cost": {
    "estimated_model_calls": 0,
    "actual_model_calls": 0,
    "network_request_count": 0
  }
}
```

推荐同时写出分阶段 artifact：

- `claims.json`：ClaimExtractionResult；
- `evidence.json`：RetrievalResult、EvidenceDecision 和 adapter failures；
- `fact-review.json`：FactReviewInput、reviewer availability 和 call metadata；
- `reconciliation.json`：按 Claim ID 对齐的最终状态、manual review metadata 和 citations；
- `run-manifest.json`：配置摘要、版本、预算和 artifact 路径。

所有引用必须来自已有 evidence chunk；artifact 不保存 API key 或未经必要脱敏的敏感模型响应正文。

## 7. Benchmark 设计

M3 应新增离线 report-level benchmark fixture，覆盖：

- Markdown heading、paragraph、list、code block 和 URL；
- 稳定 Claim ID 和 extraction statistics；
- 有证据、无证据、冲突证据和 invalid citation；
- retrieval、decision、adapter 和 reviewer failure slots；
- Fact A/B isolation 和 reconciliation status。

Benchmark 分为两层：

1. offline deterministic benchmark：不调用模型、不访问网络，验证完整 orchestration 和 artifact schema；
2. live validation：仅在显式确认后执行，复用既有 Dual Fact live workflow，并记录 planned/actual calls、network requests 和 runtime。

不得修改已有 v0.3.1/v0.4 M2 benchmark fixture；新增 report-level benchmark 通过 adapter 组合既有 fixture 或独立 fixture 验证。

## 8. 成本控制

M3 必须在执行前完成成本估算：

- Claim extraction 不调用模型；
- Evidence retrieval 优先离线 cache；
- Evidence retrieval 和 decision 每个 Claim 至多执行一次；
- Fact A/B 按 batch 调用，不按 Claim 单独调用；
- Coordinator preflight 超预算时不调用 reviewer；
- 不进行无意义 retry；
- network request count 和 model call count 分阶段记录。

基线目标保持与 M2.2 一致：Fact A/B 仍按既有 batch 计划执行，live validation 目标为 8 model calls、0 evidence network requests。

## 9. 不修改范围

M3 不修改：

- Claim schema；
- `EvidenceDecisionEngine`；
- `DualFactReviewCoordinator`；
- Fact A/B reviewer prompt 和 provider 核心逻辑；
- Reconciliation 规则；
- 既有 benchmark fixture。

如果需要新的字段或 artifact metadata，应放在 orchestration result/config 层，并通过显式 adapter 传递，不向下游隐式注入字段。

## 10. 验收标准

- `verify-report report.md` 能从 Markdown 生成完整 report-level artifact；
- 每个 Claim 从 extraction 到 reconciliation 保持 Claim ID 对齐；
- failure Claim 可追踪且不进入 reviewer；
- Fact A/B 输入独立，输出不互相污染；
- offline benchmark 零模型、零网络通过；
- live validation 在确认后满足预算和调用约束；
- v0.3.1 Dual Fact benchmark 回归通过。

## 11. Artifact schema contract

`report-verification.json` 是一次 report-level run 的主 artifact，必须包含以下顶层字段：

```json
{
  "metadata": {},
  "claims": {},
  "evidence": {},
  "fact_review": {},
  "reconciliation": {},
  "statistics": {}
}
```

字段 contract：

- `metadata`：schema version、run ID、source file、source name、execution mode、config summary 和时间信息；
- `claims`：ClaimExtractionResult 及 extraction metadata，包括 heading path、line range、confidence、method 和 extraction statistics；
- `evidence`：逐 Claim 的 RetrievalResult、EvidenceDecision 和 evidence failure；
- `fact_review`：逐 Claim 的 `fact_a`、`fact_b`、reviewer availability、call metadata 和 failure slots；
- `reconciliation`：所有 Claim 的最终记录，包括成功结果和失败结果；每条记录至少包含 `claim_id`、`status`、`needs_manual_review`、`failure_stage` 和 `failure_code`；
- `statistics`：total/ready/failed Claim 数量、status distribution、estimated/actual model calls、network request count、runtime 和 budget 状态。

Artifact 必须同时保留成功结果和 failure Claim，不能只输出进入 reviewer 的 Claim。模型响应正文不得未经必要脱敏直接保存。

## 12. Claim ID 全链路约束

每个阶段必须使用同一个稳定 `claim_id`，并保持 ClaimRegistry 顺序：

```text
ClaimExtraction.claim_id
  = Evidence.claim_id
  = FactReviewInput.claim["claim_id"]
  = Fact A.claim_id
  = Fact B.claim_id
  = Reconciliation.claim_id
```

Orchestrator 必须在阶段边界校验 Claim ID。缺失、重复或错配的 ID 进入 failure record，不得按列表位置静默覆盖。Fact A/B 的 reviewer 输出不能覆盖 orchestrator 保存的原始 Claim ID。

## 13. CLI execution policy

- `--offline`：只限制 evidence network retrieval；它不改变本地 extraction、decision 或已确认的 reviewer execution policy；
- `--dry-run`：只执行 extraction、planning 和 budget estimate，不调用 Fact A/B reviewer，不执行 live model call；
- `--confirm-live-model-calls`：显式允许 Fact A/B reviewer 调用；未提供时不得执行真实 reviewer call；
- `--confirm-planned-call-count N`：在 reviewer 调用前校验 preflight 估算调用数必须等于 `N`，否则终止执行且不调用 reviewer。

CLI 必须拒绝含义冲突的运行模式，并在 artifact metadata 中记录最终 execution mode 和 budget decision。

## 14. Orchestrator 单一职责

Report-level orchestrator 只负责调用已有模块、传递显式 contract、执行阶段 preflight，以及按 ClaimRegistry 顺序合并结果。它：

- 不实现 retrieval；
- 不实现 EvidenceDecision；
- 不实现 reconciliation；
- 不自动 retry failure Claim；
- 不修改 Claim schema、EvidenceDecision status 或 Reconciliation 规则；
- 不向 Fact A/B 注入对方输出；
- 必须保留并汇总每一阶段的 failure slots；
- 必须按 ClaimRegistry 顺序生成最终 artifact。

## 15. M3 milestone split

M3 保留三阶段拆分：

- **M3.1 Offline orchestration**：实现 extraction、planning、Evidence Adapter、Fact Adapter 的离线组合，验证 Claim ID、failure slots、零模型和零网络约束；
- **M3.2 Report-level Dual Fact execution**：接入现有 Coordinator 和 Reconciliation，验证 Fact A/B isolation、batch budget、call metadata 和 failure routing；
- **M3.3 CLI and validation**：实现 `verify-report`、artifact persistence、offline benchmark 和显式确认后的 live validation。

后续阶段不得提前改变已有 Claim schema、EvidenceDecisionEngine、DualFactReviewCoordinator 或 v0.3.1 benchmark contract。