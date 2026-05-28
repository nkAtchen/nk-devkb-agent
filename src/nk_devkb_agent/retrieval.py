from __future__ import annotations

from .models import SearchResult
from .store import KnowledgeStore


class LocalRetriever:
    def __init__(self, store: KnowledgeStore, top_k: int = 5) -> None:
        self.store = store
        self.top_k = top_k

    def search(self, namespace: str, query: str, top_k: int | None = None) -> list[SearchResult]:
        return self.store.search_chunks(namespace, query, top_k or self.top_k)

    def rerank(self, query: str, results: list[SearchResult], top_k: int | None = None) -> list[SearchResult]:
        limit = top_k or self.top_k
        return sorted(results, key=lambda item: (-item.score, len(item.text), item.title))[:limit]
