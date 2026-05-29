from __future__ import annotations

from pathlib import Path

from .chunking import MarkdownChunker
from .config import RuntimeConfig
from .documents import DocumentConverter
from .llm import DEFAULT_SYSTEM_PROMPT, LocalLLMClient, create_llm_client
from .models import Answer, CollectionSchedule, SearchResult
from .reflection import ReflectionGate
from .retrieval import LocalRetriever
from .store import KnowledgeStore


DEFAULT_NAMESPACE = "default"


class RAGTool:
    def __init__(
        self,
        *,
        store: KnowledgeStore,
        namespace: str = DEFAULT_NAMESPACE,
        converter: DocumentConverter | None = None,
        chunker: MarkdownChunker | None = None,
        retriever: LocalRetriever | None = None,
        llm: LocalLLMClient | None = None,
        reflection: ReflectionGate | None = None,
    ) -> None:
        self.store = store
        self.namespace = namespace
        self.converter = converter or DocumentConverter()
        self.chunker = chunker or MarkdownChunker()
        self.retriever = retriever or LocalRetriever(store)
        self.llm = llm or LocalLLMClient()
        self.reflection = reflection or ReflectionGate()
        self.store.ensure_schema()
        self.store.upsert_namespace(namespace, root_dir=self.store.db_path.parent)

    def init_namespace(self, namespace: str | None = None, root_dir: Path | str | None = None) -> None:
        ns = namespace or self.namespace
        self.store.ensure_schema()
        self.store.upsert_namespace(ns, root_dir or self.store.db_path.parent)

    def ingest_file(self, path: Path | str, namespace: str | None = None) -> str:
        ns = namespace or self.namespace
        document = self.converter.convert(path)
        source_id = self.store.upsert_source(
            namespace=ns,
            kind="local_file",
            locator=str(document.source_path),
            title=document.title,
            status="ready",
            content_hash=document.content_hash,
        )
        self.store.delete_chunks_for_source(ns, source_id)
        for chunk in self.chunker.chunk(document):
            self.store.upsert_chunk(
                namespace=ns,
                source_id=source_id,
                heading_path=chunk.heading_path,
                position=chunk.position,
                text=chunk.text,
                text_hash=chunk.text_hash,
                token_count=chunk.token_count,
            )
        return source_id

    def search(self, query: str, namespace: str | None = None, top_k: int = 5) -> list[SearchResult]:
        return self.retriever.search(namespace or self.namespace, query, top_k)

    def ask(self, user_prompt: str, namespace: str | None = None) -> Answer:
        ns = namespace or self.namespace
        candidates = self.retriever.search(ns, user_prompt, top_k=8)
        evidence = self.retriever.rerank(user_prompt, candidates, top_k=4)
        if evidence:
            answer_text = self.llm.synthesize_with_evidence(user_prompt, evidence)
            reflection = self.reflection.check(answer_text=answer_text, used_rag=True, evidence=evidence)
            if not reflection.passed:
                return Answer(
                    text=f"Answer withheld: {'; '.join(reflection.reasons)}",
                    used_rag=True,
                    no_rag_context=False,
                    reflection=reflection,
                    citations=[],
                )
            return Answer(
                text=answer_text,
                used_rag=True,
                no_rag_context=False,
                reflection=reflection,
                citations=[self._citation(result) for result in evidence],
            )

        answer_text = self.llm.synthesize_without_evidence(user_prompt, DEFAULT_SYSTEM_PROMPT)
        reflection = self.reflection.check(answer_text=answer_text, used_rag=False, evidence=[])
        if not reflection.passed:
            return Answer(
                text=f"Answer withheld: {'; '.join(reflection.reasons)}",
                used_rag=False,
                no_rag_context=True,
                reflection=reflection,
                citations=[],
            )
        return Answer(
            text=answer_text,
            used_rag=False,
            no_rag_context=True,
            reflection=reflection,
            citations=[],
        )

    def summarize(self, namespace: str | None = None, target: str = "collection", doc_id: str | None = None) -> str:
        ns = namespace or self.namespace
        if target == "file" and doc_id:
            chunks = self.store.chunks_for_source_target(ns, doc_id)
            title = doc_id
        else:
            chunks = self.store.all_chunks(ns)
            title = ns
        return self.llm.summarize(title, [chunk.text for chunk in chunks])

    def sources(self, namespace: str | None = None):
        return self.store.list_sources(namespace or self.namespace)

    def refresh(self, namespace: str | None = None) -> str:
        ns = namespace or self.namespace
        sources = self.store.list_sources(ns)
        refreshed = 0
        for source in sources:
            path = Path(source.locator)
            if path.exists():
                self.ingest_file(path, ns)
                refreshed += 1
        return f"refreshed {refreshed} source(s)"

    def configure_daily_schedule(
        self,
        *,
        namespace: str | None = None,
        daily_at: str = "12:00",
        timezone: str = "local",
    ) -> CollectionSchedule:
        hour, minute = daily_at.split(":", 1)
        cron_expr = f"{int(minute)} {int(hour)} * * *"
        ns = namespace or self.namespace
        schedule = CollectionSchedule(
            schedule_id=f"{ns}:daily",
            namespace=ns,
            cron_expr=cron_expr,
            timezone=timezone,
            enabled=True,
        )
        self.store.save_schedule(schedule)
        return schedule

    def schedules(self, namespace: str | None = None) -> list[CollectionSchedule]:
        return self.store.list_schedules(namespace or self.namespace)

    def run_scheduled_collection(self, namespace: str | None = None) -> str:
        return self.refresh(namespace or self.namespace)

    def _citation(self, result: SearchResult) -> dict[str, object]:
        return {
            "source_id": result.source_id,
            "title": result.title,
            "locator": result.locator,
            "heading_path": result.heading_path,
            "chunk_id": result.chunk_id,
            "score": result.score,
        }


def create_rag_pipeline(
    *,
    db_path: Path | str,
    namespace: str = DEFAULT_NAMESPACE,
    llm: LocalLLMClient | None = None,
    config: RuntimeConfig | None = None,
) -> RAGTool:
    runtime_config = config or RuntimeConfig.from_root(Path(db_path).parent.parent)
    return RAGTool(
        store=KnowledgeStore(db_path),
        namespace=namespace,
        llm=llm or create_llm_client(runtime_config),
    )
