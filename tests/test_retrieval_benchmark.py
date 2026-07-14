from pathlib import Path

from agent_network.evidence.retrieval_benchmark import (
    run_retrieval_benchmark,
    write_retrieval_benchmark,
)


FIXTURE = Path("benchmarks/fixtures/retrieval-v1")


def test_offline_retrieval_benchmark_is_repeatable_and_isolated(tmp_path) -> None:
    first = run_retrieval_benchmark(FIXTURE)
    second = run_retrieval_benchmark(FIXTURE)

    assert first.to_dict() == second.to_dict()
    assert first.metrics.total_cases == 20
    assert first.network_request_count == first.model_call_count == 0
    assert first.metrics.forbidden_hit_rate == 0
    assert first.metrics.budget_compliance_rate == 1
    paths = write_retrieval_benchmark(first, tmp_path)
    assert all(path.is_file() for path in paths)
