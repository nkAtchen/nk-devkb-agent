from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from nk_devkb_agent.multiagent import (
    ResearchCoordinator,
    ToolRegistry,
    run_search_agent,
    run_summarize_agent,
)
from nk_devkb_agent.store import KnowledgeStore


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def arxiv_feed(*papers) -> bytes:
    entries = []
    for arxiv_id, title, summary, published in papers:
        entries.append(
            f"""
      <entry>
        <id>http://arxiv.org/abs/{arxiv_id}</id>
        <published>{published}</published>
        <title>{title}</title>
        <summary>{summary}</summary>
        <author><name>Alice</name></author>
      </entry>"""
        )
    xml = f"""<?xml version='1.0' encoding='utf-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>{''.join(entries)}
    </feed>"""
    return xml.encode("utf-8")


def feed_opener():
    body = arxiv_feed(
        ("2401.12345v1", "RAG Retrieval", "retrieval augmented generation", "2024-01-09T00:00:00Z"),
        ("2402.54321v2", "Agent Memory", "long term memory for agents", "2024-02-10T00:00:00Z"),
    )

    def fake_open(request, timeout=30):
        return FakeResponse(body)

    return fake_open


FINISH_RESULTS = [
    {
        "arxiv_id": "2401.12345v1",
        "title": "RAG Retrieval",
        "abstract": "retrieval augmented generation",
        "year": 2024,
        "authors": "Alice, Bob",
        "url": "http://arxiv.org/abs/2401.12345v1",
        "score": 0.9,
        "reason": "top",
    },
    {
        "arxiv_id": "2402.54321v2",
        "title": "Agent Memory",
        "abstract": "long term memory for agents",
        "year": 2024,
        "authors": "Carol",
        "url": "http://arxiv.org/abs/2402.54321v2",
        "score": 0.7,
        "reason": "mid",
    },
]


class SearchLLM:
    """Single-shot search sub-agent: emit one query, nothing else."""

    def chat(self, messages, temperature=0.2) -> str:
        content = messages[-1]["content"]
        if "搜索角度" in content:
            return json.dumps({"query": "retrieval augmented generation"}, ensure_ascii=False)
        return "{}"


class CoordinatorLLM:
    """Scripts every LLM step in the coordinator's phase machine."""

    def __init__(self, *, queries=None, selected=None, summary=None) -> None:
        self.queries = queries or ["retrieval augmented generation", "dense retrieval"]
        self.selected = selected or ["2401.12345", "2402.54321"]
        self.summary = summary or '{"problem_method": "研究检索", "summary": "作者做了检索", "conclusion": "检索有效"}'
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def chat(self, messages, temperature=0.2) -> str:
        last = messages[-1]
        role, content = last["role"], last["content"]
        with self._lock:
            self.calls.append((role, content))
        if role == "user" and "拆成" in content:
            return json.dumps({"queries": self.queries}, ensure_ascii=False)
        if role == "user" and "候选论文" in content:
            return json.dumps({"selected": self.selected, "reason": "best"}, ensure_ascii=False)
        if role == "user" and "搜索角度" in content:
            return json.dumps({"query": "retrieval augmented generation"}, ensure_ascii=False)
        if role == "user" and "problem_method" in content:
            return self.summary
        return "{}"


class BrokenChatLLM:
    def chat(self, messages, temperature=0.2) -> str:
        raise RuntimeError("boom")


def build_coordinator(tmp_path, llm, **kwargs) -> tuple[ResearchCoordinator, KnowledgeStore]:
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    store.ensure_schema()
    coordinator = ResearchCoordinator(
        store,
        llm,
        arxiv_base_url="http://export.arxiv.org/api/query",
        opener=feed_opener(),
        max_results_per_agent=5,
        **kwargs,
    )
    return coordinator, store


# --- tool registry ----------------------------------------------------------


def test_tool_registry_scopes_tools():
    registry = ToolRegistry({"arxiv_search": lambda query: f"result:{query}"})

    assert registry.call("arxiv_search", "rag") == "result:rag"

    with pytest.raises(KeyError):
        registry.call("summarize")


# --- search sub-agent ReAct --------------------------------------------------


def test_run_search_agent_queries_then_fetches():
    fetched = []

    def record(query):
        fetched.append(query)
        return "[arxiv_search] 没有搜到结果。"

    registry = ToolRegistry({"arxiv_search": record})
    llm = SearchLLM()

    results = run_search_agent(llm, "RAG", "retrieval", registry, context_window=100000)

    assert results == []
    assert fetched == ["retrieval augmented generation"]


def test_run_search_agent_degrades_when_the_llm_is_broken():
    registry = ToolRegistry({"arxiv_search": lambda query: "x"})

    results = run_search_agent(BrokenChatLLM(), "RAG", "retrieval", registry, context_window=100000, max_steps=2)

    assert results == []


def test_run_search_agent_degrades_on_malformed_actions():
    class GarbageLLM:
        def chat(self, messages, temperature=0.2) -> str:
            return "not json at all"

    registry = ToolRegistry({"arxiv_search": lambda query: "x"})

    results = run_search_agent(GarbageLLM(), "RAG", "retrieval", registry, context_window=100000, max_steps=2)

    assert results == []


# --- summarize sub-agent -----------------------------------------------------


def test_run_summarize_agent_parses_the_template():
    class SummaryLLM:
        def chat(self, messages, temperature=0.2) -> str:
            return '{"problem_method": "P", "summary": "S", "conclusion": "C"}'

    paper = {"arxiv_id": "2401.12345v1", "title": "T", "year": 2024, "authors": "A", "abstract": "abs", "url": "u"}

    summary = run_summarize_agent(SummaryLLM(), paper, context_window=100000)

    assert summary.arxiv_id == "2401.12345"
    assert summary.source == "arXiv:2401.12345"
    assert summary.problem_method == "P"
    assert summary.summary == "S"
    assert summary.conclusion == "C"


# --- coordinator end-to-end --------------------------------------------------


def test_coordinator_normalizes_none_opener(tmp_path):
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    store.ensure_schema()

    coordinator = ResearchCoordinator(
        store, CoordinatorLLM(), arxiv_base_url="http://export.arxiv.org/api/query", opener=None
    )

    assert coordinator.opener is urllib.request.urlopen


def test_coordinator_research_end_to_end(tmp_path):
    coordinator, store = build_coordinator(tmp_path, CoordinatorLLM())

    summaries = coordinator.research("RAG", "demo", top_n=2, search_agents=2)

    ids = sorted(summary.arxiv_id for summary in summaries)
    assert ids == ["2401.12345", "2402.54321"]
    assert summaries[0].problem_method == "研究检索"
    assert summaries[0].source == "arXiv:2401.12345"
    assert sorted(s.arxiv_id for s in store.list_paper_summaries("demo")) == ids


def test_coordinator_research_persists_and_resumes(tmp_path):
    coordinator, store = build_coordinator(tmp_path, CoordinatorLLM())

    run_id = "run-123"
    coordinator.research("RAG", "demo", run_id=run_id, top_n=2, search_agents=2)

    # A second call with the same run id is a no-op that still returns the stored
    # summaries without re-planning or re-searching.
    second = coordinator.research("RAG", "demo", run_id=run_id, top_n=2, search_agents=2)

    assert [s.arxiv_id for s in second] == ["2401.12345", "2402.54321"]
    assert store.load_research_session(run_id)["phase"] == "done"
    # The stored messages round-trip back into a session.
    assert store.load_session_messages(run_id)


def test_coordinator_resumes_from_a_saved_phase(tmp_path):
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    store.ensure_schema()
    llm = CoordinatorLLM()
    coordinator = ResearchCoordinator(
        store,
        llm,
        arxiv_base_url="http://export.arxiv.org/api/query",
        opener=feed_opener(),
        max_results_per_agent=5,
    )

    # Seed a session that already planned and searched, then resume it.
    store.upsert_research_session(
        "run1", "demo", "RAG", phase="searched", state=json.dumps({"candidates": FINISH_RESULTS})
    )
    store.save_session_messages("run1", [{"role": "user", "content": "研究主题：RAG"}])

    summaries = coordinator.research("RAG", "demo", run_id="run1", top_n=2, search_agents=2)

    assert sorted(s.arxiv_id for s in summaries) == ["2401.12345", "2402.54321"]
    # Plan and search were skipped; only selection and summarization ran.
    assert not any("拆成" in content for _, content in llm.calls)
    assert not any("搜索角度" in content for _, content in llm.calls)
    assert any("候选论文" in content for _, content in llm.calls)


def test_search_backfills_full_metadata_from_fetch(tmp_path):
    # Candidates now come straight from the deterministic fetch, so title/authors/
    # year/url reach the summarizer without any model output carrying them.
    coordinator, store = build_coordinator(tmp_path, CoordinatorLLM())

    summaries = coordinator.research("RAG", "demo", top_n=2, search_agents=2)

    by_id = {summary.arxiv_id: summary for summary in summaries}
    assert by_id["2401.12345"].title == "RAG Retrieval"
    assert by_id["2401.12345"].authors == "Alice"
    assert by_id["2401.12345"].year == 2024
    assert by_id["2401.12345"].url == "http://arxiv.org/abs/2401.12345v1"


def test_select_mode_score_skips_llm_select(tmp_path):
    llm = CoordinatorLLM()
    coordinator, store = build_coordinator(tmp_path, llm, select_mode="score")

    summaries = coordinator.research("RAG", "demo", top_n=2, search_agents=2)

    assert sorted(s.arxiv_id for s in summaries) == ["2401.12345", "2402.54321"]
    # Deterministic select must not issue the LLM "候选论文" call.
    assert not any("候选论文" in content for _, content in llm.calls)


def test_grounding_gate_records_verdicts(tmp_path):
    # One summary reuses its abstract's anchors (grounded), the other shares none
    # (ungrounded). The gate records both without blocking persistence.
    llm = CoordinatorLLM(
        summary='{"problem_method": "RAG retrieval augmented generation", '
        '"summary": "authors improved retrieval", "conclusion": "generation works"}'
    )
    coordinator, store = build_coordinator(tmp_path, llm, grounding_gate=True)

    coordinator.research("RAG", "demo", top_n=2, search_agents=2)

    statuses = {r["arxiv_id"]: r["status"] for r in coordinator.grounding_results}
    assert statuses["2401.12345"] == "grounded"
    assert statuses["2402.54321"] == "ungrounded"
    # Observation-only: the gate must not drop a summary.
    assert sorted(s.arxiv_id for s in store.list_paper_summaries("demo")) == ["2401.12345", "2402.54321"]


# --- plan drift gate ---------------------------------------------------------


class FakeEmbeddingClient:
    """Returns pre-normalized 2-D vectors so the gate's dot product is a cosine."""

    def __init__(self, vectors_by_text: dict[str, list[float]]) -> None:
        self.vectors_by_text = vectors_by_text

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors_by_text.get(text, [0.0, 0.0]) for text in texts]


def test_guard_queries_rule_tier_drops_zero_overlap(tmp_path):
    coordinator, _ = build_coordinator(tmp_path, CoordinatorLLM())

    kept = coordinator._guard_queries(
        "retrieval augmented generation",
        ["retrieval augmented generation", "image segmentation"],
    )

    assert kept == ["retrieval augmented generation"]
    assert any("image segmentation" in note for note in coordinator.dropped_queries)


def test_guard_queries_embedding_tier_drops_low_cosine(tmp_path):
    client = FakeEmbeddingClient(
        {
            "retrieval augmented generation": [1.0, 0.0],
            "retrieval models": [0.0, 1.0],
            "retrieval systems": [1.0, 0.0],
        }
    )
    coordinator, _ = build_coordinator(tmp_path, CoordinatorLLM(), embedding_client=client)

    kept = coordinator._guard_queries(
        "retrieval augmented generation",
        ["retrieval models", "retrieval systems"],
    )

    assert kept == ["retrieval systems"]
    assert any("retrieval models" in note for note in coordinator.dropped_queries)


def test_guard_queries_falls_back_to_topic_when_all_dropped(tmp_path):
    coordinator, _ = build_coordinator(tmp_path, CoordinatorLLM())

    kept = coordinator._guard_queries("retrieval augmented generation", ["image segmentation"])

    assert kept == ["retrieval augmented generation"]


def test_guard_queries_skips_embedding_tier_when_no_client(tmp_path):
    coordinator, _ = build_coordinator(tmp_path, CoordinatorLLM())

    # Shares a token with the topic, so the rule tier keeps it; no embedding
    # client means the semantic tier is skipped and it survives.
    kept = coordinator._guard_queries("retrieval augmented generation", ["retrieval ranking"])

    assert kept == ["retrieval ranking"]
    assert not any("embedding 层" in note for note in coordinator.dropped_queries)


# --- relevance scoring (embedding) -------------------------------------------


def test_score_by_relevance_uniform_when_no_embedding_client(tmp_path):
    coordinator, _ = build_coordinator(tmp_path, CoordinatorLLM())

    papers = [
        {"arxiv_id": "2402.54321v2", "abstract": "long term memory for agents"},
        {"arxiv_id": "2401.12345v1", "abstract": "retrieval augmented generation"},
    ]

    scored = coordinator._score_by_relevance("RAG", papers)

    # No embedding client: every paper scores 1.0 and fetch order is preserved.
    assert [p["score"] for p in scored] == [1.0, 1.0]
    assert [p["arxiv_id"] for p in scored] == ["2402.54321v2", "2401.12345v1"]


def test_score_by_relevance_orders_by_cosine(tmp_path):
    # Topic shares a dimension with paper A's abstract but not paper B's, so A
    # must rank first (dot product on pre-normalized vectors == cosine).
    client = FakeEmbeddingClient(
        {
            "retrieval": [1.0, 0.0],
            "image segmentation": [0.0, 1.0],
            "retrieval augmented generation": [1.0, 0.0],
        }
    )
    coordinator, _ = build_coordinator(tmp_path, CoordinatorLLM(), embedding_client=client)

    papers = [
        {"arxiv_id": "2402.54321v2", "abstract": "image segmentation"},
        {"arxiv_id": "2401.12345v1", "abstract": "retrieval augmented generation"},
    ]

    scored = coordinator._score_by_relevance("retrieval", papers)

    assert [p["arxiv_id"] for p in scored] == ["2401.12345v1", "2402.54321v2"]
    assert scored[0]["score"] == 1.0
    assert scored[1]["score"] == 0.0


# --- L3 semantic re-anchor ---------------------------------------------------


def test_summarize_history_returns_summary_and_degrades(tmp_path):
    class SummaryChatLLM:
        def chat(self, messages, temperature=0.2) -> str:
            return "研究 RAG，选了 2401.12345"

    coordinator, _ = build_coordinator(tmp_path, SummaryChatLLM())
    assert coordinator._summarize_history([{"role": "user", "content": "研究主题：RAG"}]) == "研究 RAG，选了 2401.12345"

    broken, _ = build_coordinator(tmp_path, BrokenChatLLM())
    assert broken._summarize_history([{"role": "user", "content": "x"}]) == ""
