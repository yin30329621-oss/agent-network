"""Small deterministic benchmark metrics for EvidenceDecision outcomes."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from agent_network.claim.evidence_decision import EvidenceDecision, EvidenceDecisionStatus


@dataclass(frozen=True, slots=True)
class EvidenceDecisionBenchmarkMetrics:
    total_cases: int
    correct_status_count: int
    precision: float
    citation_accuracy: float
    manual_review_rate: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def benchmark_decisions(
    expected_statuses: list[EvidenceDecisionStatus], decisions: list[EvidenceDecision]
) -> EvidenceDecisionBenchmarkMetrics:
    if len(expected_statuses) != len(decisions):
        raise ValueError("Benchmark expectations and decisions must have the same length")
    total = len(decisions)
    correct = sum(
        expected == decision.status
        for expected, decision in zip(expected_statuses, decisions, strict=True)
    )
    citations = sum(bool(decision.evidence) for decision in decisions)
    manual = sum(
        decision.status == EvidenceDecisionStatus.MANUAL_REVIEW_REQUIRED for decision in decisions
    )
    return EvidenceDecisionBenchmarkMetrics(
        total,
        correct,
        correct / total if total else 0.0,
        citations / total if total else 0.0,
        manual / total if total else 0.0,
    )
