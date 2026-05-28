from __future__ import annotations

from .models import SearchResult


DEFAULT_SYSTEM_PROMPT = (
    "You are a local knowledge-base agent. Answer clearly. "
    "When no retrieved context exists, mark the answer as no_rag_context."
)


class LocalLLMClient:
    def synthesize_with_evidence(self, question: str, evidence: list[SearchResult]) -> str:
        snippets = []
        for index, result in enumerate(evidence, start=1):
            text = " ".join(result.text.split())
            snippets.append(f"[{index}] {text}")
        return (
            f"Answer based on retrieved evidence for: {question}\n\n"
            + "\n".join(snippets)
        )

    def synthesize_without_evidence(self, user_prompt: str, default_system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
        return (
            "no_rag_context\n"
            f"System prompt: {default_system_prompt}\n"
            f"User prompt: {user_prompt}\n"
            "No local knowledge-base evidence matched this request, so this is a fallback response."
        )

    def summarize(self, title: str, texts: list[str]) -> str:
        joined = " ".join(" ".join(text.split()) for text in texts)
        preview = joined[:500]
        return f"Summary for {title}: {preview}" if preview else f"Summary for {title}: no content."
