# Agent Network v0.4 Rancher Live Validation Baseline

**Benchmark date:** 2026-07-22  
**Benchmark name:** Rancher Security Review Live Validation v0.4 / 30 Claims  
**Scope:** Report-level Claim Extraction, offline Evidence Retrieval, Dual Fact A/B, Security, Logic, and Merge  
**Repository:** `/home/yin/agent-network`

## 1. Benchmark configuration

- Selected Claims: 30
- Batch size: 3 Claims per Fact reviewer batch
- Fact batches: 10 for Fact A and 10 for Fact B
- Evidence source: local Rancher evidence cache with offline BM25 retrieval
- Evidence network requests: 0
- Logic timeout: 180 seconds
- Logic retry attempts: 1
- JSON-only request policy: enabled for Security, Logic, and Merge

## 2. Models

| Agent | Provider | Model |
|---|---|---|
| Fact A | deepseek_official | `deepseek-v4-pro` |
| Fact B | dashscope_official | `qwen3.7-plus` |
| Security | siliconflow | `Pro/moonshotai/Kimi-K2.6` |
| Logic | siliconflow | `deepseek-ai/DeepSeek-V4-Flash` |
| Merge | siliconflow | `zai-org/GLM-5.2` |

## 3. Agent execution flow

```text
Rancher Markdown report
  → deterministic Claim Extraction
  → deterministic high-value Claim selection
  → offline BM25 Evidence Retrieval
  → Fact A / Fact B independent batch review
  → local Fact reconciliation
  → Security Agent
  → Logic Agent
  → Merge Agent
```

Fact A and Fact B receive independent deep-copy inputs and do not share reviewer
outputs. The evidence pipeline retains Claim IDs and evidence chunk IDs for
traceability. Security, Logic, and Merge execute sequentially with checkpoint
artifacts.

## 4. Execution results

- Fact A: 30/30 parsed
- Fact B: 30/30 parsed
- Fact reconciliation: 7 consensus, 23 reviewer disagreements
- Security: completed, 3 findings
- Logic: completed, 7 findings
- Merge: completed, 10 merged findings
- Workflow status: completed
- Actual model calls: 23
  - Fact A: 10
  - Fact B: 10
  - Security: 1
  - Logic: 1
  - Merge: 1
- Runtime: 799.98 seconds
- Evidence network requests: 0

This baseline records the completed run represented by the case-local output
artifacts and `run-metadata.json`. It is a validation benchmark, not a formal
security audit conclusion.

## 5. Token estimates

| Metric | Estimate |
|---|---:|
| Fact A total input tokens | 43,157 |
| Fact B total input tokens | 43,157 |
| Maximum Fact batch input | 7,422 |
| Fact batch count | 6 in preflight metadata; 10 reviewer batches in this live run configuration |
| Logic input tokens | 8,903 |
| Security input tokens | Not recorded by runner |
| Merge input tokens | Not recorded by runner |
| Evidence traceability | true |

The Logic input estimate reflects the compressed Logic context. Provider output
tokens and hidden reasoning tokens are not used as baseline estimates here.

## 6. Difference from the v0.3.1 baseline

The v0.3.1 baseline established an 19-Claim Dual Fact checkpoint with Fact A and
Fact B only, four batches (`5, 5, 5, 4`), eight model calls, and zero evidence
network requests.

This v0.4 baseline differs in the following ways:

- Expands the benchmark from 19 to 30 Claims.
- Uses batch size 3, resulting in 10 Fact A and 10 Fact B reviewer calls.
- Adds report-level deterministic Claim Extraction and high-value Claim selection.
- Adds local EvidenceDecision and offline BM25 evidence retrieval before Fact review.
- Executes Security, Logic, and Merge after Fact reconciliation.
- Increases the completed-run call count from 8 to 23.
- Preserves the zero evidence-network-request constraint.
- Preserves independent Fact A/B execution and Claim/evidence traceability.
- Adds sequential checkpoint artifacts for intermediate agent results and failures.

The v0.4 benchmark therefore measures the integrated report-level workflow,
while v0.3.1 primarily measured the Dual Fact verification checkpoint.

## 7. Artifact reference

- `cases/rancher-security-review-live-v1/output/claims.json`
- `cases/rancher-security-review-live-v1/output/evidence-retrieval.json`
- `cases/rancher-security-review-live-v1/output/fact-review.json`
- `cases/rancher-security-review-live-v1/output/security-review.json`
- `cases/rancher-security-review-live-v1/output/logic-review.json`
- `cases/rancher-security-review-live-v1/output/merge-result.json`
- `cases/rancher-security-review-live-v1/output/run-metadata.json`

