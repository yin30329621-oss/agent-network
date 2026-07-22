# Logic Agent Regression Audit

## Scope

This audit uses existing artifacts from the latest 30-claim validation. It does not modify production code, call a model, or run a new live validation.

## 1. Provider and Model

- Provider: siliconflow
- Model: deepseek-ai/DeepSeek-V4-Flash
- Configured max tokens: 1600
- Temperature: 0
- Response format: JSON object
- Timeout: 180 seconds
- Retry: 1

The Logic request has no explicit thinking or enable_thinking parameter. SiliconFlow documents reasoning_effort high/max for this V4 Flash model, but its documented enable_thinking model list does not include this model. No unverified disable parameter should be added. See https://docs.siliconflow.cn/cn/api-reference/chat-completions/chat-completions.

## 2. Observed Failure

- Prompt tokens: 21,408
- Completion tokens: 1,600
- Total tokens: 23,008
- finish_reason: length
- truncated_response: true
- Content length: 4,108
- Attempts: 2
- Final status: parse_failed
- Parsed findings: 0

The final attempt reached the configured completion-token ceiling. This proves output-budget exhaustion, but does not prove how much hidden reasoning consumed the budget.

## 3. Prompt Composition Estimate

The case runner sends the same compact review context to Security and Logic; it does not append a separate Security result to the Logic request. Estimates use approximately four characters per token.

| Component | Characters | Estimated tokens | Approx. share of Logic user prompt |
|---|---:|---:|---:|
| System prompt | 1,875 | 469 |
| Claims | 9,689 | 2,423 |
| Evidence references/excerpts | 32,348 | 8,087 |
| Fact A/B structured results | 8,544 | 2,136 |
| Instruction/source/other context | 143 | 36 |
| User prompt total | 50,779 | 12,695 | 100% |

Estimated Logic system plus user total: approximately 13,164 tokens. Observed provider prompt usage was 21,408 tokens.

## 4. Security Prompt versus Logic Prompt

Additional Logic content:

- More extensive instructions for premises, contradictions, missing steps, and argument strength.
- A larger review schema including the reference field.
- More permission to explain reasoning quality and argument flow.

Repeated content:

- Claim list
- Evidence references and excerpts
- Fact A/B results
- JSON-only instruction and source label

Compression candidates:

1. Pass claim IDs plus compact Fact A/B status, reason, and cited chunk IDs.
2. Pass evidence references only for claims flagged by Fact A/B.
3. Shorten the Logic system instructions and cap the finding count.
4. Forbid repeated evidence and long explanations.

Security completed with 19,880 prompt tokens and finish_reason stop. Logic used 21,408 prompt tokens and reached the output ceiling. The current runner shares the same claim/evidence/fact context between the two agents.

## 5. Root-Cause Assessment

| Hypothesis | Assessment |
|---|---|
| A. Thinking consumption | Possible because no explicit disable is configured; not proven because Logic audit exposed reasoning_content_length 0. |
| B. Prompt too long | Contributing factor: about 21.4k input tokens and 30 claims plus evidence and dual-review context. |
| C. JSON output too long | Strongest direct cause: completion reached exactly max_tokens=1600 and stopped with length. |
| D. Provider hard limit | Not established; the provider returned normal usage telemetry without a context-limit error. |

Conclusion: most consistent with C amplified by B. A remains possible; D is unsupported by current telemetry.

## 6. Minimal Fix Proposal

1. Do not add an unverified thinking-disable parameter for this SiliconFlow V4 Flash route.
2. Remove duplicated Logic context and pass only compact Fact A/B results plus disputed-claim evidence.
3. Tighten the JSON output contract: bounded findings, short fields, JSON-only, no repeated evidence or explanations.
4. Preserve timeout, retry, and checkpoint behavior.
5. Consider smaller context partitions only if truncation remains.

No change is proposed to Claim schema, Fact A/B isolation, Security, Merge, EvidenceDecision, or provider adapter.

## 7. Existing Artifact Reference

- security-review.json: completed
- logic-review.json: parse_failed / truncated_response
- merge-result.json: incomplete because Logic failed
- Evidence network requests: 0
