# Rancher Report Benchmark v1

本 Benchmark 使用人工标注的 `FIXTURE ONLY` Claim 集合和既有 `retrieval-v1/chunks.json` 离线证据 Chunk，复用 Offline BM25 Retriever 与现有保守 Verification Policy。它不调用 Fact A/B，不访问网络，也不代表真实官方文档或模型准确率。

## 数据

共 19 条 Claim，覆盖 Cluster Agent、Reverse Tunnel、RBAC、ServiceAccount、Registration Token、TLS、Fleet Agent、Bundle、CVE、Release Notes、产品隔离、绝对化表述、错误引用、版本不匹配、不可用和 extraction failure。

每条样本的人工 ground truth 独立记录 `expected_status`、`expected_relation`、`expected_chunk_ids`、`forbidden_chunk_ids`、理由、局限和难度。证据 ID 必须来自既有 fixture，不为 benchmark 新造证据。

## 运行

```powershell
uv run python -m benchmarks.rancher_report_benchmark --output benchmarks/results-local/rancher-report-v1
```

输出 `benchmark.json`、`benchmark.md` 和 `run.json`。不指定 `--output` 时只打印确定性指标 JSON。

## 指标

- `exact_status_accuracy`：实际状态与人工期望状态完全相同的比例。
- `relation_accuracy`：实际 Evidence Relation 与期望完全相同的比例。
- `citation_precision/recall`：实际引用与期望 Chunk ID 的集合精确率/召回率。
- `unsupported_citation_count`：未出现在期望集合中的实际引用数量。
- `agreement_rate`：状态和关系同时匹配的比例。
- `auto_resolve_rate/manual_review_rate`：当前 candidate-only 策略的自动解决与人工复核比例。
- `per_status`：按期望状态统计 expected、actual、exact。

## 当前限制

BM25 相关性不能自动升级为 `verified_supported` 或 `verified_contradicted`；因此明确支持和明确反驳样本会暴露当前 Engine 与人工标签之间的差距。CVE、Release Notes 和版本事实仍需外部核验。后续真实双 Fact Benchmark 应在此基线之上运行，而不是替换本 Benchmark 的人工期望。
