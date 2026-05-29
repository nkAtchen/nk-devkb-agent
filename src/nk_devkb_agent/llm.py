from __future__ import annotations

import json
import urllib.error
import urllib.request

from .config import RuntimeConfig
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


class OpenAICompatibleLLMClient(LocalLLMClient):
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def synthesize_with_evidence(self, question: str, evidence: list[SearchResult]) -> str:
        context = self._format_context(evidence)
        user_content = (
            "请优先基于下面的 RAG 检索上下文回答用户问题。\n\n"
            f"RAG 检索上下文：\n{context}\n\n"
            f"用户问题：\n{question}"
        )
        return self._chat(user_content)

    def synthesize_without_evidence(self, user_prompt: str, default_system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
        user_content = (
            f"{default_system_prompt}\n\n"
            "没有检索到可用的 RAG 上下文，请直接回答用户问题，并明确这是 no_rag_context。\n\n"
            f"用户问题：\n{user_prompt}"
        )
        response = self._chat(user_content)
        return response if "no_rag_context" in response else f"no_rag_context\n{response}"

    def _format_context(self, evidence: list[SearchResult]) -> str:
        lines = []
        for index, item in enumerate(evidence, start=1):
            heading = " / ".join(item.heading_path)
            lines.append(
                "\n".join(
                    [
                        f"[{index}] source={item.title}",
                        f"heading={heading}",
                        f"text={item.text}",
                    ]
                )
            )
        return "\n\n".join(lines)

    def _chat(self, user_content: str) -> str:
        url = self.config.llm_base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.llm_model,
            "messages": [
                {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.llm_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc
        return str(body["choices"][0]["message"]["content"])


def create_llm_client(config: RuntimeConfig) -> LocalLLMClient:
    if config.use_remote_llm():
        return OpenAICompatibleLLMClient(config)
    return LocalLLMClient()
