from __future__ import annotations

from .models import ReflectionResult, SearchResult


class ReflectionGate:
    def check(self, *, answer_text: str, used_rag: bool, evidence: list[SearchResult]) -> ReflectionResult:
        if not answer_text.strip():
            return ReflectionResult(
                passed=False,
                reasons=["answer is empty"],
                suggested_action="refuse",
            )
        if used_rag and not evidence:
            return ReflectionResult(
                passed=False,
                reasons=["rag answer has no evidence"],
                suggested_action="refuse",
            )
        if not used_rag and "no_rag_context" not in answer_text:
            return ReflectionResult(
                passed=False,
                reasons=["fallback answer is missing no_rag_context marker"],
                suggested_action="refuse",
            )
        return ReflectionResult(passed=True, reasons=["passed"], suggested_action="present")
