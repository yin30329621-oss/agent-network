"""LangGraph review workflow."""

from __future__ import annotations

from dataclasses import dataclass
import time
from collections.abc import Callable
from typing import TypedDict

from agent_network.agents import FactAgent, LogicAgent, MergeAgent, ReviewerAgent, SecurityAgent
from agent_network.llm import LLMClient
from agent_network.prompts import PromptRegistry
from agent_network.schemas import AgentReview, ReviewFinding, ReviewRequest, ReviewResult, Severity

ProgressCallback = Callable[[str, str, float | None, AgentReview | None], None]


class ReviewState(TypedDict, total=False):
    request: ReviewRequest
    fact: AgentReview
    security: AgentReview
    logic: AgentReview
    merged: AgentReview


@dataclass(slots=True)
class ReviewWorkflow:
    """Coordinates the MVP reviewer agents."""

    fact_agent: ReviewerAgent
    security_agent: ReviewerAgent
    logic_agent: ReviewerAgent
    merge_agent: MergeAgent

    @classmethod
    def from_llm(cls, *, llm: LLMClient, prompts: PromptRegistry) -> "ReviewWorkflow":
        return cls(
            fact_agent=FactAgent(llm=llm, prompts=prompts),
            security_agent=SecurityAgent(llm=llm, prompts=prompts),
            logic_agent=LogicAgent(llm=llm, prompts=prompts),
            merge_agent=MergeAgent(prompts=prompts, llm=llm),
        )

    @classmethod
    def from_config(cls, *, llm: LLMClient, prompts: PromptRegistry, config) -> "ReviewWorkflow":
        return cls(
            fact_agent=FactAgent(
                llm=llm,
                prompts=prompts,
                model=config.model_for_agent("fact"),
                provider=config.provider_for_agent("fact"),
                timeout_seconds=config.timeout_for_agent("fact"),
            ),
            security_agent=SecurityAgent(
                llm=llm,
                prompts=prompts,
                model=config.model_for_agent("security"),
                provider=config.provider_for_agent("security"),
                timeout_seconds=config.timeout_for_agent("security"),
            ),
            logic_agent=LogicAgent(
                llm=llm,
                prompts=prompts,
                model=config.model_for_agent("logic"),
                provider=config.provider_for_agent("logic"),
                timeout_seconds=config.timeout_for_agent("logic"),
            ),
            merge_agent=MergeAgent(
                prompts=prompts,
                llm=llm,
                model=config.model_for_agent("merge"),
                provider=config.provider_for_agent("merge"),
                timeout_seconds=config.timeout_for_agent("merge"),
            ),
        )

    def run_sequential(
        self, request: ReviewRequest, progress: ProgressCallback | None = None
    ) -> ReviewResult:
        reviews = [
            self._run_agent("fact", self.fact_agent, request, 1, 3, progress),
            self._run_agent("security", self.security_agent, request, 2, 3, progress),
            self._run_agent("logic", self.logic_agent, request, 3, 3, progress),
        ]
        merged = self.merge_agent.merge(reviews)
        return self._result_from_merge(reviews, merged)

    def run_only(
        self, request: ReviewRequest, agent_name: str, progress: ProgressCallback | None = None
    ) -> ReviewResult:
        agents = {
            "fact": self.fact_agent,
            "security": self.security_agent,
            "logic": self.logic_agent,
        }
        if agent_name == "merge":
            fixture_reviews = _merge_fixture_reviews()
            return self.run_merge_only(fixture_reviews, progress=progress)
        if agent_name not in agents:
            raise ValueError(
                f"Unknown agent {agent_name!r}. Expected fact, security, logic, or merge."
            )
        review = self._run_agent(agent_name, agents[agent_name], request, 1, 1, progress)
        merged = self.merge_agent.merge([review])
        return self._result_from_merge([review], merged)

    def run_merge_only(
        self, reviews: list[AgentReview], progress: ProgressCallback | None = None
    ) -> ReviewResult:
        if progress:
            progress("1/1:merge", "start", None, None)
        start = time.monotonic()
        try:
            merged = self.merge_agent.merge(reviews)
            merged.status = "completed"
            merged.elapsed_seconds = time.monotonic() - start
            if progress:
                progress("merge", "complete", merged.elapsed_seconds, merged)
            return ReviewResult(
                summary=merged.summary,
                agent_reviews=[*reviews, merged],
                findings=merged.findings,
                merged_findings=self.merge_agent.last_merged_findings,
                disagreements=self.merge_agent.last_disagreements,
                execution_notes=_execution_notes([*reviews, merged]),
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            merged = AgentReview(
                agent="merge",
                summary="Merge Agent did not complete.",
                status="failed",
                model=self.merge_agent.model,
                provider=self.merge_agent.provider,
                elapsed_seconds=elapsed,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            if progress:
                progress("merge", "failed", elapsed, merged)
            return ReviewResult(
                summary=merged.summary, agent_reviews=[*reviews, merged], findings=[]
            )

    def run(self, request: ReviewRequest, progress: ProgressCallback | None = None) -> ReviewResult:
        reviews = [
            self._run_agent("fact", self.fact_agent, request, 1, 4, progress),
            self._run_agent("security", self.security_agent, request, 2, 4, progress),
            self._run_agent("logic", self.logic_agent, request, 3, 4, progress),
        ]
        if progress:
            progress("4/4:merge", "start", None, None)
        start = time.monotonic()
        merged = self.merge_agent.merge(reviews)
        merged.elapsed_seconds = time.monotonic() - start
        merged.status = "completed"
        merged.model = merged.model or self.merge_agent.model
        merged.provider = merged.provider or self.merge_agent.provider
        if progress:
            progress("merge", "complete", merged.elapsed_seconds, merged)
        return self._result_from_merge(reviews, merged)

    def _result_from_merge(self, reviews: list[AgentReview], merged: AgentReview) -> ReviewResult:
        all_reviews = [*reviews, merged]
        return ReviewResult(
            summary=merged.summary,
            agent_reviews=all_reviews,
            findings=merged.findings,
            merged_findings=self.merge_agent.last_merged_findings,
            disagreements=self.merge_agent.last_disagreements,
            execution_notes=_execution_notes(all_reviews),
        )

    def _run_agent(
        self,
        agent_name: str,
        agent: ReviewerAgent,
        request: ReviewRequest,
        index: int,
        total: int,
        progress: ProgressCallback | None,
    ) -> AgentReview:
        if progress:
            progress(f"{index}/{total}:{agent_name}", "start", None, None)
        start = time.monotonic()
        model = getattr(agent, "model", None)
        try:
            review = agent.review(request)
            review.status = review.status or "completed"
            review.model = review.model or model
            review.elapsed_seconds = time.monotonic() - start
            if progress:
                progress(agent_name, "complete", review.elapsed_seconds, review)
            return review
        except Exception as exc:
            elapsed = time.monotonic() - start
            review = AgentReview(
                agent=agent_name,
                summary=f"{agent_name.title()} Agent did not complete.",
                status="failed",
                model=model,
                provider=getattr(agent, "provider", None),
                elapsed_seconds=elapsed,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            if progress:
                progress(agent_name, "failed", elapsed, review)
            return review

    def _build_graph(self):
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return None

        graph = StateGraph(ReviewState)

        def fact(state: ReviewState) -> ReviewState:
            return {"fact": self.fact_agent.review(state["request"])}

        def security(state: ReviewState) -> ReviewState:
            return {"security": self.security_agent.review(state["request"])}

        def logic(state: ReviewState) -> ReviewState:
            return {"logic": self.logic_agent.review(state["request"])}

        def merge(state: ReviewState) -> ReviewState:
            return {
                "merged": self.merge_agent.merge([state["fact"], state["security"], state["logic"]])
            }

        graph.add_node("fact", fact)
        graph.add_node("security", security)
        graph.add_node("logic", logic)
        graph.add_node("merge", merge)
        graph.set_entry_point("fact")
        graph.add_edge("fact", "security")
        graph.add_edge("security", "logic")
        graph.add_edge("logic", "merge")
        graph.add_edge("merge", END)
        return graph.compile()


def _merge_fixture_reviews() -> list[AgentReview]:
    return [
        AgentReview(
            agent="fact",
            summary="Fact review found claims that need evidence or qualification.",
            findings=[
                ReviewFinding(
                    agent="fact",
                    severity=Severity.MEDIUM,
                    location="Reliability Claim",
                    issue="RollingUpdate is described as guaranteeing zero downtime.",
                    evidence_needed="Readiness probe, PodDisruptionBudget, rollout logs, and capacity evidence.",
                    suggestion="Qualify the claim and document the required operational conditions.",
                    confidence=0.88,
                )
            ],
        ),
        AgentReview(
            agent="security",
            summary="Security review found risky Kubernetes defaults.",
            findings=[
                ReviewFinding(
                    agent="security",
                    severity=Severity.HIGH,
                    location="Summary",
                    issue="The service account is granted cluster-admin access.",
                    evidence_needed="Exact RBAC verbs and resource scope required by the workload.",
                    suggestion="Use least-privilege Role or ClusterRole bindings.",
                    confidence=0.95,
                )
            ],
        ),
        AgentReview(
            agent="logic",
            summary="Logic review found unsupported reasoning.",
            findings=[
                ReviewFinding(
                    agent="logic",
                    severity=Severity.MEDIUM,
                    location="Container Configuration",
                    issue="Autoscaling is used as a reason to omit resource limits.",
                    evidence_needed="Scheduling, quota, and noisy-neighbor control assumptions.",
                    suggestion="Separate cluster scaling from per-container resource governance.",
                    confidence=0.86,
                )
            ],
        ),
    ]


def _execution_notes(reviews: list[AgentReview]) -> list[str]:
    notes: list[str] = []
    for review in reviews:
        if review.status == "parse_failed":
            notes.append(
                f"{review.agent.title()} Agent call completed but structured parsing failed."
            )
        elif review.status not in {"completed", "valid"}:
            notes.append(
                f"{review.agent.title()} Agent status is {review.status}: {review.error_type or 'unknown'}."
            )
    return notes
