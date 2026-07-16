# v0.4 M2 Design: Report-level Verification

状态：设计文档（不包含实现）  
范围：v0.4 Milestone 2  
前置版本：v0.4 M1 Markdown Report → Claim Extraction

## 1. v0.4 M2 目标

M2 将 M1 产生的 ClaimRegistry 接入现有 Evidence Verification 和 Dual Fact Review Pipeline：

Markdown Report → Claim Extraction → ClaimRegistry → Evidence Retrieval → EvidenceDecisionEngine → FactReviewInput → Fact A / Fact B → Local Reconciliation

M2 的重点是报告级编排和边界适配，不重新实现 Claim 抽取、证据规则或四-agent workflow。每个 Claim 必须保留稳定的 claim_id 和来源元数据，证据引用必须受现有 chunk_id 约束。M2 不增加 agent、模型调用或证据网络请求。

## 2. 当前 v0.3.1 Verification Pipeline

v0.3.1 中需要区分两条相关但不同的路径。M2 通过 adapter 和编排连接它们，不替换现有 pipeline。

### Path A：Claim Verification

ClaimRegistry → ClaimVerificationEngine → ClaimVerificationBatchResult → Fact Context

Path A 负责基于本地官方 evidence cache 的 Claim 级检索和确定性验证结果。ClaimVerificationEngine 产生 ClaimVerificationBatchResult，随后由现有 Fact context builder 生成受限的 Fact context。

### Path B：Dual Fact Review

ClaimRegistry → RetrievalResult → EvidenceDecisionEngine → FactReviewInput → Dual Fact → Reconciliation

Path B 使用 RetrievalResult 和 EvidenceDecisionEngine 生成 Fact A/B 的共同输入，再由 Dual Fact reviewer 独立调用，最后交给本地 Reconciliation。它是 evidence-constrained review 路径，不应被误解为替换 Path A。

M2 的职责是新增报告级编排和 adapter，使 M1 的 ClaimRegistry 可以按明确 contract 进入 Path A、Path B 或两者的受控组合；不改变 v0.3.1 已有 pipeline 的 API、规则或调用计划。

当前流程以 Claim 为输入：

1. 从 Claim 生成 ClaimRetrievalQuery。
2. Retriever 从离线 evidence cache 中检索 RetrievalResult；只有显式允许时才使用网络。
3. EvidenceDecisionEngine 批量判断证据覆盖、充分性、引用合法性和允许的验证状态。
4. 决策结果生成 FactReviewInput。
5. Fact A 和 Fact B 接收相同且独立复制的输入，分别批处理调用。
6. 本地 Reconciliation 归一化 reviewer 状态、应用 evidence gating，并生成 manual review 路由。

EvidenceDecisionEngine 是确定性的 gating 约束层；模型 reviewer 不能通过不受支持的证据或不存在的引用升级结果。Dual Fact coordinator 本身只负责独立调用计划和本地汇总，不替代四-agent Fact / Security / Logic / Merge workflow。

## 3. ClaimRegistry → Evidence Pipeline 数据流

推荐的数据流如下：

- ClaimRegistry：按稳定插入顺序提供 canonical Claim 列表。
- ClaimRetrievalQuery：通过现有 query_for_claim() 从每个 Claim 生成查询。
- RetrievalResult：按 claim_id 对齐返回候选 evidence、来源和检索元数据。
- (Claim, RetrievalResult)：作为 EvidenceDecisionEngine.decide_batch() 的输入。
- EvidenceDecisionBatch：包含每 Claim 的证据决策、状态计数和 review_inputs。
- FactReviewInput：作为 Fact A/B 的唯一共同输入边界。
- DualFactReviewCoordinator：按预先计算的 batch 计划独立调用 Fact A/B。
- Reconciliation：只在两路结果完成后进行本地确定性汇总。

适配层必须保持 ClaimRegistry 的顺序和 ID，不因检索排序改变 Claim 结果顺序。检索失败也要保留对应 Claim 的结果槽位，以便审计和人工复核。不得从模型输出或已裁剪的 Fact prompt 重新构造 Claim。

## 4. EvidenceDecisionEngine adapter 设计

M2 建议增加一个薄的报告级编排模块：

src/agent_network/claim/report_verification.py

它只组合现有 contract，建议提供以下职责：

- build_retrieval_pairs(registry, retriever, limits)：批量建立 Claim 与 RetrievalResult 的 ID 对齐关系。
- build_evidence_decisions(pairs, engine)：调用现有 decide_batch()。
- build_dual_fact_review_inputs(decision_batch)：直接使用 EvidenceDecisionBatch.review_inputs。
- run_dual_fact_review(review_inputs, reviewers, budget)：交给现有 coordinator 执行。
- reconcile_report_results(...)：复用现有本地 reconciliation 结果，并保留 Claim ID。

适配层不得复制 evidence sufficiency、citation validation、status gating、batch planning 或 retry 规则。EvidenceDecisionEngine 的 decision、rule audit、evidence status 和限制信息应原样进入可审计结果。

### Adapter Config contract

adapter 应接收一个显式配置 contract，至少包含：

- cache directory；
- document filters，包括 document IDs、document type、product 或 component；
- top-k、max documents 和每文档 chunk 限制；
- evidence limits，包括每条 evidence 和每批 evidence 的字符或数量上限；
- offline/network policy，默认只允许本地 evidence，网络必须显式开启；
- verification mode；
- DualReviewBudget，包括 batch size、最大 batch 数、输入和输出 token 预算。

配置必须在运行前完成校验和调用估算。adapter 不应隐式采用另一套默认检索参数，也不应在 live mode 下自动放宽网络或预算限制。

### Evidence consistency rules

- Claim、RetrievalResult、EvidenceDecision 和 FactReviewInput 必须按同一 claim_id 对齐；
- decision 中的 evidence 与 retrieval 中用于展示和审计的 evidence 必须来自同一检索结果；
- reviewer 的 citation 校验和 prompt 中展示的 evidence 必须使用同一组已验证 chunk_id；
- adapter 不得覆盖或重新解释 EvidenceDecisionEngine 产生的 status、sufficiency、rule audit 或 limitations；
- retrieval 失败、空 evidence 和被裁剪的 evidence 必须保留 Claim 级结果槽位，不得通过位置变化掩盖失败。

adapter 应优先直接传递 EvidenceDecisionBatch.review_inputs，不根据 retrieval 或 Fact 输出再次构造 decision。

## 5. FactReviewInput contract

FactReviewInput 是 Evidence Decision 与 Fact Reviewer 之间的稳定边界，包含：

- claim：canonical Claim 的可序列化表示，至少包括 claim_id、文本、来源和位置。
- decision：EvidenceDecisionEngine 的状态、置信度、充分性、规则审计和允许的结论范围。
- retrieval：与 Claim 对齐的 evidence 摘要及检索元数据。

每个输入中的 claim_id 必须在三部分一致。Evidence 内容必须有已存在的 chunk_id，并可包含 document_id、canonical URL、文本摘要、rank 和匹配信息；不得注入完整原始文档、未验证 URL 或模型生成的引用。输入应使用现有 EvidenceDecisionBatch.review_inputs，避免生成第二套近似 schema。

## 6. Dual Fact 独立性保证

Fact A 和 Fact B 必须：

- 接收相同 Claim、Evidence、Decision 和 Verification Engine 输入；
- 使用独立的深拷贝或不可变快照；
- 使用独立 batch 调用和结果容器；
- 在调用前不读取对方输入、状态或输出；
- 仅在两路调用结束后交给本地 Reconciliation。

实现应保留可审计的输入摘要或哈希，便于验证 A/B 输入一致；结果记录中不能把 A 的输出拼入 B 的 prompt。一路失败不触发另一路的隐式重试，也不使用共享 judge 模型替代本地 reconciliation。

FactReviewInput 的嵌套字典在 contract 层视为只读。交给 Fact A 和 Fact B 前必须分别创建独立 deep copy；任何一方对输入的修改都不得影响另一方或本地 reconciliation。测试必须验证 A/B 输入内容相同、对象独立、嵌套 evidence 独立，并验证 A 的输出不会出现在 B 的输入中。

## 7. Batch 调用和成本控制

M2 沿用现有 batch 和 DualReviewBudget 约束：

- 运行前根据 Claim 数、batch size 和 Fact A/B 路数估算调用数；
- 禁止每个 Claim 单独调用模型；
- 预算超限时在首个 live call 前失败；
- 不增加自动 retry，失败分类由结果层记录；
- 限制每批 Claim 数、evidence 数、输入长度和输出 token；
- 明确区分 dry-run、离线验证和需确认的 live mode；
- 记录 model call、evidence network call、batch 数和运行时间。

adapter 禁止重复执行已有 retrieval 或 decision：如果 Path A 已经产生可复用的 ClaimVerificationBatchResult 或其 evidence 结果，后续编排必须明确选择复用结果或进入 Path B 的独立 contract，不得因为格式转换再次检索同一 Claim 或重复执行同一 decision。需要同时保留两条路径时，也必须记录每条路径的调用计数，并证明没有无意义的重复网络请求或模型调用。

若有 N 个 batch，Fact A/B 各调用 N 次，总模型调用为 2N。现有 Rancher Dual Fact 基线为 19 个 Claim、batch [5, 5, 5, 4]、8 次模型调用、0 次 evidence 网络请求；M2 接入不得改变这组计划。

## 8. 不修改模块范围

M2 第一阶段不修改：

- claim.py 的 canonical Claim schema；
- extractor.py、segmentation.py 和 registry.py 的 M1 行为；
- EvidenceDecisionEngine 的既有规则；
- Fact model adapter、Fact A/B prompt 和 provider 配置；
- fact_review.py 的 Dual Fact 独立调用与本地 reconciliation 语义；
- Fact / Security / Logic / Merge 四-agent workflow；
- 现有 benchmark fixture、batch size 和调用确认机制；
- 证据 fetch、clean、chunk、BM25 retriever 的基础实现。

优先新增报告级 orchestration adapter 与测试，避免把 M2 需求扩散到稳定模块。

## 9. 测试和验收标准

离线单元测试应覆盖：

- ClaimRegistry 顺序、稳定 ID 和空 registry；
- Claim 与 RetrievalResult 的 ID 对齐，以及检索失败的保留槽位；
- EvidenceDecisionBatch 字段和 review_inputs 的完整传递；
- 无效 citation、证据不足和不同 evidence status 的 gating；
- FactReviewInput 中 Claim、Decision、Retrieval 的 ID 一致性；
- Fact A/B 输入内容和哈希相同、对象独立，且一方输出不会污染另一方；
- 单路失败、批次失败和预算超限不产生额外调用；
- 19 Claim 的 dry-run 仍计划 8 次模型调用、0 次网络 evidence 请求；
- 现有 v0.3.1 fixtures 和 benchmark API 继续可用。

验收条件：

- M1 输出的 ClaimRegistry 可直接进入 M2，不创建第二套 Claim schema；
- 每个 Claim 都有可追踪的 retrieval、decision 和 reconciliation 结果；
- evidence gating 和 citation 约束在 reviewer 结果之前生效；
- 既有 pytest、Ruff 和离线 benchmark 通过；
- live benchmark 仅在显式确认后执行，并验证调用数不变。

## 10. 潜在风险

- VerificationResult、Fact context 和 FactReviewInput 字段边界不一致，造成重复序列化或信息丢失；
- 检索排序、部分失败或截断导致 Claim ID 与 evidence 错位；
- 报告规模扩大后，单批输入和 evidence budget 超限；
- provider 的 JSON 或 thinking 输出影响 reviewer parse，但不应由 adapter 自动修补；
- 未验证的报告 URL 或模型生成 citation 污染 evidence contract；
- 误把 report-level orchestration 变成 per-Claim 调用或隐式 retry，破坏成本基线；
- 超长 Markdown 在抽取和检索阶段增加运行时间。

推荐的最小实现是新增薄的 report_verification 编排层，复用现有 Claim、retrieval、EvidenceDecisionEngine、FactReviewInput、DualFactReviewCoordinator 和本地 Reconciliation；先完成离线 contract/isolation/budget 测试，再进行 live validation。
