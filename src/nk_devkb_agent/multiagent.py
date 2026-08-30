from __future__ import annotations

import json
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Callable

from .jsonutil import extract_json_object
from .models import PaperSummary
from .reflection import grounding_verdict, invented_quantities
from .session import DEFAULT_COMPRESS_RATIO, AgentSession
from .store import KnowledgeStore, tokenize
from .tools.arxiv import ArxivCollectionError, arxiv_dedupe_key, collect_arxiv_items

# ---------------------------------------------------------------------------
# Master/slave research. The main agent is an LLM that carries a persistent
# session; search sub-agents generate one query and fetch deterministically;
# summarize sub-agents are single-shot. Deterministic downloads stay in
# `collect_arxiv_items` -- the LLM never performs the download itself, and it
# never scores relevance either: that is done centrally with embedding cosine
# similarity (`_score_by_relevance`), so arxiv_ids always come from the fetch,
# never from the model's output.
#
# Session separation: the main agent's `AgentSession` accumulates across phases
# and is persisted for resume; each sub-agent gets a throwaway `AgentSession`
# that holds only its own brief + tool results and is discarded after it
# returns. Sub-agents report *structured results*, never their reasoning
# transcript, so the main agent's window only grows by bounded artifacts.
# ---------------------------------------------------------------------------


# --- structured output (tool calling) ---------------------------------------

# The 7B model cannot reliably emit balanced JSON as free text (it drops fields,
# corrupts keys, mis-nests arrays), so every structured step asks the model to
# *call a function* whose arguments are a schema-enforced JSON object -- the
# provider then guarantees valid JSON and the required keys. `_structured_json`
# falls back to text-JSON parsing for the mock client and offline degrade path.


def _function_tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    """Build one OpenAI-compatible `tools` entry (a single function)."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


PLAN_TOOL = _function_tool(
    "submit_plan",
    "把研究主题拆成若干搜索角度",
    {"queries": {"type": "array", "items": {"type": "string"}, "description": "英文检索短语列表"}},
    ["queries"],
)

SELECT_TOOL = _function_tool(
    "submit_selection",
    "从候选论文中挑选最合适的论文",
    {
        "selected": {"type": "array", "items": {"type": "string"}, "description": "选中的 arxiv_id 列表"},
        "reason": {"type": "string", "description": "选择理由"},
    },
    ["selected"],
)

SUMMARIZE_TOOL = _function_tool(
    "submit_summary",
    "提交论文中文总结",
    {
        "problem_method": {"type": "string", "description": "论文研究的问题与方法"},
        "summary": {"type": "string", "description": "作者做了什么，结果如何"},
        "conclusion": {"type": "string", "description": "结论的核心观点"},
    },
    ["problem_method", "summary", "conclusion"],
)

SEARCH_QUERY_TOOL = _function_tool(
    "submit_query",
    "输出一个英文检索短语",
    {"query": {"type": "string", "description": "英文检索短语"}},
    ["query"],
)


def _structured_json(llm, messages: list[dict], tool: dict, temperature: float = 0.2) -> dict | None:
    """Get a structured dict from the model: tool calling first, text-JSON fallback.

    Tool calling is the reliable path (schema-enforced); the fallback covers the
    mock client and any remote failure, so a broken provider never aborts a step.
    """
    chat_with_tools = getattr(llm, "chat_with_tools", None)
    if chat_with_tools is not None:
        try:
            args = chat_with_tools(messages, [tool], temperature=temperature)
        except Exception:
            args = None
        if args is not None:
            return args
    try:
        raw = llm.chat(messages, temperature=temperature)
    except Exception:
        return None
    return extract_json_object(raw)


# --- tool registry (role-scoped) --------------------------------------------


class ToolRegistry:
    """Deterministic tools an agent is allowed to call.

    Role scoping is enforced by construction: a search sub-agent is handed a
    registry containing only `arxiv_search`; a summarizer gets no registry; the
    coordinator never exposes storage/derivation tools to a sub-agent. There is
    deliberately no global singleton.
    """

    def __init__(self, tools: dict[str, Callable[..., str]]) -> None:
        self._tools = tools

    def call(self, name: str, *args: object, **kwargs: object) -> str:
        fn = self._tools.get(name)
        if fn is None:
            raise KeyError(f"tool not available in this scope: {name}")
        return fn(*args, **kwargs)


def make_arxiv_search_tool(
    *,
    max_results: int,
    base_url: str,
    timeout: int,
    fetcher: str,
    opener,
    known_ids: list[str],
    metadata_by_id: dict[str, dict] | None = None,
) -> Callable[[str], str]:
    def arxiv_search(query: str) -> str:
        try:
            items = collect_arxiv_items(
                query,
                max_results=max_results,
                base_url=base_url,
                timeout=timeout,
                fetcher=fetcher,
                opener=opener,
                known_ids=known_ids,
            )
        except ArxivCollectionError as exc:
            return f"[arxiv_search error] {exc}"
        if metadata_by_id is not None:
            # One setitem per item is atomic under the GIL, and duplicate ids
            # write identical data, so concurrent search agents sharing this map
            # are safe without a lock.
            for item in items:
                meta = _item_metadata(item)
                metadata_by_id[arxiv_dedupe_key(meta["arxiv_id"])] = meta
        # The coordinator reads `metadata_by_id` for arxiv_ids and full metadata;
        # this return string is only a status marker (the model no longer reads a
        # result listing, so no per-item display text is formatted here).
        return f"[arxiv_search] {len(items)} results"

    return arxiv_search


def _item_metadata(item) -> dict:
    """Deterministic per-item fields the coordinator needs after fetch.

    The search sub-agent only fetches; the coordinator scores relevance from
    `abstract` and the summarizer reads every field, so authors/year/url are kept
    here rather than echoed back through the model's output.
    """
    metadata = item.metadata or {}
    arxiv_id = str(metadata.get("arxiv_id", item.id.removeprefix("arxiv-")))
    authors = metadata.get("authors", [])
    authors_text = ", ".join(str(a) for a in authors) if isinstance(authors, list) else str(authors)
    published = str(metadata.get("published_at", ""))
    year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else 0
    return {
        "arxiv_id": arxiv_id,
        "title": item.title,
        "abstract": item.raw_description,
        "authors": authors_text,
        "year": year,
        "url": item.url,
    }


# --- search sub-agent (single-shot) ----------------------------------------

SEARCH_QUERY_SYSTEM = "你是论文检索子 agent。给定研究主题和搜索角度，输出一个英文检索短语。"


def run_search_agent(
    llm,
    topic: str,
    angle: str,
    registry: ToolRegistry,
    *,
    context_window: int,
    compress_ratio: float = DEFAULT_COMPRESS_RATIO,
    max_steps: int = 4,
) -> list[dict]:
    """A search sub-agent as two single-shot steps: one query, one fetch.

    The 7B model corrupts multi-turn ReAct (it emitted `" xiv_search"` after a
    tool result and never finished), so the loop is replaced by: generate one
    query -> deterministic fetch. Relevance scoring is *not* done here anymore --
    the model cannot reliably emit a ranked `arxiv_id` list (it corrupts ids and
    times out on the array-of-objects schema), so the coordinator scores every
    fetched paper centrally with embedding cosine similarity
    (`_score_by_relevance`).

    `context_window`/`compress_ratio`/`max_steps` are kept for signature
    compatibility with the previous ReAct loop; the single-shot design no longer
    loops, so they are unused.
    """
    # 1. One search phrase for this angle.
    query_payload = _structured_json(
        llm,
        [
            {"role": "system", "content": SEARCH_QUERY_SYSTEM},
            {"role": "user", "content": f"研究主题：{topic}\n搜索角度：{angle}"},
        ],
        SEARCH_QUERY_TOOL,
    )
    query = str((query_payload or {}).get("query", "")).strip() or topic
    # 2. Deterministic fetch -- the model never downloads anything itself. The
    #    tool populates `metadata_by_id` (read by the coordinator); the returned
    #    listing string is no longer fed back to the model, so it is discarded.
    registry.call("arxiv_search", query)
    return []


# --- summarize sub-agent (single-shot) --------------------------------------

SUMMARIZE_SYSTEM = "你是论文总结子 agent，只输出 JSON，不要输出其他文字；每个字段一句话、不超过 100 字。"

SUMMARIZE_USER = """根据下面的论文元数据，用中文总结这篇论文，填入模板字段。

标题：{title}
年份：{year}
作者：{authors}
出处：{source}
摘要：{abstract}

只输出 JSON，不要有其他文字；每个字段一句话、不超过 100 字：
{{"problem_method": "论文研究的问题与方法", "summary": "作者做了什么，结果如何", "conclusion": "结论的核心观点"}}"""


def run_summarize_agent(llm, paper: dict, *, context_window: int) -> PaperSummary:
    arxiv_id = arxiv_dedupe_key(str(paper.get("arxiv_id", "")))
    source = f"arXiv:{arxiv_id}"
    prompt = SUMMARIZE_USER.format(
        title=paper.get("title", "未知"),
        year=paper.get("year") or "未知",
        authors=paper.get("authors", "未知"),
        source=source,
        abstract=paper.get("abstract", ""),
    )
    messages = [
        {"role": "system", "content": SUMMARIZE_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    payload = _structured_json(llm, messages, SUMMARIZE_TOOL, temperature=0.2)
    problem_method = summary = conclusion = ""
    if payload is not None:
        problem_method = str(payload.get("problem_method", "")).strip()
        summary = str(payload.get("summary", "")).strip()
        conclusion = str(payload.get("conclusion", "")).strip()
    return PaperSummary(
        arxiv_id=arxiv_id,
        title=str(paper.get("title", "")),
        year=int(paper.get("year") or 0),
        source=source,
        problem_method=problem_method,
        summary=summary,
        conclusion=conclusion,
        url=str(paper.get("url", "")),
        authors=str(paper.get("authors", "")),
    )


# --- main agent (coordinator) -----------------------------------------------

# The plan drift gate's embedding-tier threshold. Same-domain-but-different-angle
# queries typically cosine ~0.4-0.7 against the topic; clearly off-topic queries
# fall below ~0.2. 0.30 sits in between and is deliberately conservative: it only
# cuts obviously-off-topic queries, not legitimate diverse angles. Model-specific,
# so it is tunable via the coordinator's `drift_min_similarity` parameter.
DRIFT_MIN_SIMILARITY = 0.30

COORDINATOR_SYSTEM = """你是论文研究协调者（主 agent）。你携带整个研究任务的上下文，负责把任务拆成搜索子任务、阅读子 agent 回传的候选论文、挑选最合适的论文，再派总结子 agent 产出总结。

你只输出 JSON，不要输出其他文字。"""

HISTORY_SUMMARY_SYSTEM = "你把一段早前的会话历史压缩成一句话摘要，保留原始研究主题、已选论文和关键决策，不展开细节。"

PLAN_USER = """研究主题：{topic}

请把这个主题拆成 {n} 个不同的搜索角度（子方向、方法、应用场景），每个角度给一个具体的英文检索短语。
只输出 JSON：{{"queries": ["角度1检索词", "角度2检索词", ...]}}"""

SELECT_USER = """下面是去重后的候选论文。请阅读后自由挑选最合适的论文（可考虑相关性、多样性、代表性），输出你选中的 arxiv_id 列表和理由。

候选论文：
{listing}

只输出 JSON：{{"selected": ["id1", "id2"], "reason": "..."}}"""


class ResearchCoordinator:
    """The master agent. Carries a persistent session; delegates to sub-agents.

    Phases run as a resumable state machine (new -> planned -> searched ->
    selected -> summarized -> done). Every LLM step degrades instead of failing,
    so offline/mock mode still completes the deterministic parts.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        llm,
        *,
        arxiv_base_url: str,
        arxiv_timeout: int = 30,
        arxiv_fetcher: str = "urllib",
        opener=None,
        max_results_per_agent: int = 5,
        context_window: int = 32768,
        compress_ratio: float = DEFAULT_COMPRESS_RATIO,
        max_steps: int = 4,
        embedding_client=None,
        drift_min_similarity: float = DRIFT_MIN_SIMILARITY,
        select_mode: str = "auto",
        grounding_gate: bool = False,
    ) -> None:
        self.store = store
        self.llm = llm
        self.arxiv_base_url = arxiv_base_url
        self.arxiv_timeout = arxiv_timeout
        self.arxiv_fetcher = arxiv_fetcher
        # Mirror PaperResearchOrchestrator: a caller that omits `opener` gets the
        # real urllib opener, not None, so `collect_arxiv_items` can always call it.
        self.opener = opener if opener is not None else urllib.request.urlopen
        self.max_results_per_agent = max_results_per_agent
        self.context_window = context_window
        self.compress_ratio = compress_ratio
        self.max_steps = max_steps
        self.embedding_client = embedding_client
        self.drift_min_similarity = drift_min_similarity
        self.select_mode = select_mode
        self.grounding_gate = grounding_gate
        self._abstract_by_id: dict[str, str] = {}
        self.grounding_results: list[dict] = []
        self.dropped_queries: list[str] = []

    # -- public ---------------------------------------------------------------

    def research(
        self,
        topic: str,
        namespace: str,
        *,
        run_id: str | None = None,
        top_n: int = 3,
        search_agents: int = 3,
    ) -> list[PaperSummary]:
        run_id = run_id or _new_run_id()
        session, phase, state, topic = self._load_or_create(run_id, namespace, topic)

        if phase == "new":
            state["queries"] = self._plan(session, topic, search_agents)
            phase = "planned"
            self._save(run_id, namespace, topic, session, phase, state)

        if phase == "planned":
            state["candidates"] = self._search(topic, namespace, state.get("queries", [topic]))
            self._inject_search_results(session, state["candidates"])
            phase = "searched"
            self._save(run_id, namespace, topic, session, phase, state)

        if phase == "searched":
            candidates = state.get("candidates", [])
            state["selected"] = self._select(session, candidates, top_n)
            phase = "selected"
            self._save(run_id, namespace, topic, session, phase, state)

        if phase == "selected":
            selected = _resolve_selected(state["selected"], state.get("candidates", []))
            state["summaries"] = [_summary_to_dict(s) for s in self._summarize(selected)]
            phase = "summarized"
            self._save(run_id, namespace, topic, session, phase, state)

        if phase == "summarized":
            summaries = [_dict_to_summary(d) for d in state.get("summaries", [])]
            self._finalize(namespace, summaries)
            phase = "done"
            self._save(run_id, namespace, topic, session, phase, state)

        return [_dict_to_summary(d) for d in state.get("summaries", [])]

    # -- persistence ----------------------------------------------------------

    def _load_or_create(self, run_id: str, namespace: str, topic: str):
        stored = self.store.load_research_session(run_id)
        if stored is not None:
            messages = self.store.load_session_messages(run_id)
            session = AgentSession.from_dicts(
                messages,
                context_window=self.context_window,
                compress_ratio=self.compress_ratio,
                summarizer=self._summarize_history,
            )
            try:
                state = json.loads(stored["state"]) if stored["state"] else {}
            except json.JSONDecodeError:
                state = {}
            # The stored topic wins on resume so a bare `--resume` never blanks it.
            return session, stored["phase"], state, stored["topic"]
        session = AgentSession(
            context_window=self.context_window,
            compress_ratio=self.compress_ratio,
            summarizer=self._summarize_history,
        )
        session.system(COORDINATOR_SYSTEM)
        session.add("user", f"研究主题：{topic}")
        return session, "new", {}, topic

    def _save(self, run_id: str, namespace: str, topic: str, session: AgentSession, phase: str, state: dict) -> None:
        self.store.upsert_research_session(
            run_id, namespace, topic, phase=phase, status="running", state=json.dumps(state, ensure_ascii=False)
        )
        self.store.save_session_messages(run_id, session.to_dicts())

    def _summarize_history(self, messages: list[dict[str, str]]) -> str:
        """Re-anchor L3 compression: fold a slice of history into one sentence."""
        if not messages:
            return ""
        text = "\n".join(f"{m.get('role', '?')}: {m.get('content', '')}" for m in messages)
        prompt = (
            "请把下面这段早前的会话历史压缩成一句话摘要，保留原始研究主题、"
            f"已选论文和关键决策。\n\n{text}"
        )
        try:
            raw = self.llm.chat(
                [
                    {"role": "system", "content": HISTORY_SUMMARY_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
        except Exception:
            return ""
        return raw.strip()

    # -- phases ---------------------------------------------------------------

    def _plan(self, session: AgentSession, topic: str, search_agents: int) -> list[str]:
        session.add("user", PLAN_USER.format(topic=topic, n=search_agents))
        payload = _structured_json(self.llm, session.render(), PLAN_TOOL)
        session.add("assistant", json.dumps(payload, ensure_ascii=False) if payload is not None else "")
        queries: list[str] = []
        if payload is not None and isinstance(payload.get("queries"), list):
            queries = [str(q).strip() for q in payload["queries"] if str(q).strip()]
        return (queries or [topic])[:search_agents]

    def _guard_queries(self, topic: str, queries: list[str]) -> list[str]:
        """Drop queries that drifted off-topic before they fan out to search.

        Two tiers, degrade-first:
        1. Rule tier (always, zero cost): a query sharing no token with the
           topic is dropped. Catches the obvious case -- a planner hallucinating
           an unrelated phrase -- without any API call.
        2. Embedding tier (only when an embedding client is provided): cosine
           similarity below `drift_min_similarity` is dropped. This is the real
           semantic detector; the caller skips it when only the mock (hashed
           bag-of-tokens) client is available, since that signal duplicates the
           rule tier.
        If every query is dropped, fall back to `[topic]` -- never fan out zero
        searches, and the topic is by definition on-topic.
        """
        if not queries:
            return [topic]

        topic_tokens = set(tokenize(topic))
        kept: list[str] = []
        for raw_query in queries:
            query = str(raw_query).strip()
            if not query:
                continue
            overlap = (
                len(topic_tokens & set(tokenize(query))) / len(topic_tokens)
                if topic_tokens
                else 0.0
            )
            if overlap == 0.0:
                self.dropped_queries.append(f"漂移闸门（规则层）：{query!r} 与主题无共享词，已丢弃。")
                continue
            kept.append(query)

        if self.embedding_client is not None and kept:
            try:
                vectors = self.embedding_client.embed([topic, *kept])
            except Exception:
                vectors = []
            if len(vectors) == len(kept) + 1:
                topic_vec = vectors[0]
                filtered: list[str] = []
                for query, query_vec in zip(kept, vectors[1:]):
                    score = sum(q * v for q, v in zip(query_vec, topic_vec))
                    if score < self.drift_min_similarity:
                        self.dropped_queries.append(
                            f"漂移闸门（embedding 层）：{query!r} 余弦 {score:.2f} < "
                            f"{self.drift_min_similarity}，已丢弃。"
                        )
                        continue
                    filtered.append(query)
                kept = filtered

        return kept or [topic]

    def _score_by_relevance(self, topic: str, papers: list[dict]) -> list[dict]:
        """Score fetched papers by embedding cosine(topic, abstract), deterministically.

        This replaces the LLM relevance judge, which the 7B model cannot run
        reliably: it corrupts arxiv_ids (e.g. `2401.12345v1` -> `0401.1345v1`) and
        times out on the array-of-objects schema. arxiv_ids therefore always come
        from the deterministic fetch; here we only order them. Without an embedding
        client -- or if the batch call fails -- every paper gets a uniform score and
        fetch order is preserved.
        """
        if not papers:
            return []
        if self.embedding_client is None:
            return [dict(paper, score=1.0) for paper in papers]
        abstracts = [str(paper.get("abstract", "")) for paper in papers]
        try:
            vectors = self.embedding_client.embed([topic, *abstracts])
        except Exception:
            vectors = []
        if len(vectors) != len(papers) + 1:
            return [dict(paper, score=1.0) for paper in papers]
        topic_vec = vectors[0]
        scored = []
        for paper, vec in zip(papers, vectors[1:]):
            # Vectors are pre-normalized, so a dot product is a cosine in [-1, 1];
            # clamp to [0, 1] so unrelated papers score 0 rather than a negative.
            score = sum(a * b for a, b in zip(topic_vec, vec))
            scored.append(dict(paper, score=max(0.0, min(1.0, score))))
        return sorted(scored, key=lambda c: -float(c["score"]))

    def _search(self, topic: str, namespace: str, queries: list[str]) -> list[dict]:
        queries = self._guard_queries(topic, queries)
        known_ids = self.store.known_arxiv_ids(namespace)
        metadata_by_id: dict[str, dict] = {}
        registry = ToolRegistry(
            {
                "arxiv_search": make_arxiv_search_tool(
                    max_results=self.max_results_per_agent,
                    base_url=self.arxiv_base_url,
                    timeout=self.arxiv_timeout,
                    fetcher=self.arxiv_fetcher,
                    opener=self.opener,
                    known_ids=known_ids,
                    metadata_by_id=metadata_by_id,
                )
            }
        )
        with ThreadPoolExecutor(max_workers=max(1, len(queries))) as executor:
            futures = [
                executor.submit(
                    run_search_agent,
                    self.llm,
                    topic=topic,
                    angle=angle,
                    registry=registry,
                    context_window=self.context_window,
                    compress_ratio=self.compress_ratio,
                    max_steps=self.max_steps,
                )
                for angle in queries
            ]
            for future in futures:
                future.result()
        # Relevance is scored centrally: the search sub-agents only fetch, and the
        # deduplicated `metadata_by_id` (keyed by arxiv_dedupe_key) is the single
        # source of arxiv_ids. Each entry already carries full metadata, so nothing
        # needs to be re-attached from the model's output.
        return self._score_by_relevance(topic, list(metadata_by_id.values()))

    def _inject_search_results(self, session: AgentSession, candidates: list[dict]) -> None:
        session.add("tool", "搜索结果（去重后）：\n" + _format_candidates(candidates))

    def _select(self, session: AgentSession, candidates: list[dict], top_n: int) -> list[str]:
        if not candidates:
            return []
        if self.select_mode == "score":
            # Deterministic select: no LLM call. The 7B model cannot reliably emit
            # the selected-id array, so sorting by the search sub-agent's score is
            # both cheaper and more dependable (see B2).
            return [c["arxiv_id"] for c in sorted(candidates, key=lambda c: -float(c.get("score") or 0))[:top_n]]
        session.add("user", SELECT_USER.format(listing=_format_candidates(candidates)))
        payload = _structured_json(self.llm, session.render(), SELECT_TOOL)
        session.add("assistant", json.dumps(payload, ensure_ascii=False) if payload is not None else "")
        selected = payload.get("selected") if payload is not None else None
        if isinstance(selected, list):
            ids = [str(item) for item in selected if str(item).strip()]
        else:
            # Degrade: fall back to the highest-scored candidates.
            ids = [c["arxiv_id"] for c in sorted(candidates, key=lambda c: -float(c.get("score") or 0))[:top_n]]
        valid = {arxiv_dedupe_key(c["arxiv_id"]): c["arxiv_id"] for c in candidates}
        return [valid[arxiv_dedupe_key(i)] for i in ids if arxiv_dedupe_key(i) in valid][:top_n]

    def _summarize(self, selected: list[dict]) -> list[PaperSummary]:
        if not selected:
            return []
        # Remember each candidate's abstract so the grounding gate can judge the
        # summary against its source without another fetch. PaperSummary drops the
        # abstract, so it is threaded here rather than through the dataclass.
        for paper in selected:
            self._abstract_by_id[arxiv_dedupe_key(str(paper.get("arxiv_id", "")))] = str(paper.get("abstract", ""))
        with ThreadPoolExecutor(max_workers=len(selected)) as executor:
            futures = [
                executor.submit(run_summarize_agent, self.llm, paper, context_window=self.context_window)
                for paper in selected
            ]
            return [future.result() for future in futures]

    def _finalize(self, namespace: str, summaries: list[PaperSummary]) -> None:
        for summary in summaries:
            if self.grounding_gate:
                self._ground_summary(summary)
            self.store.upsert_paper_summary(namespace, summary)

    def _ground_summary(self, summary: PaperSummary) -> None:
        """Record whether a summary is grounded in its paper's abstract.

        Observation-only by default: reflection's lexical check abstains often on
        Chinese summaries of English abstracts, so a wrong call must not drop a
        good summary. Results are exposed via `grounding_results` for the eval
        harness to score grounding quality without extra network calls.
        """
        abstract = self._abstract_by_id.get(arxiv_dedupe_key(summary.arxiv_id), "")
        text = " ".join(filter(None, [summary.problem_method, summary.summary, summary.conclusion]))
        if not text or not abstract:
            self.grounding_results.append({"arxiv_id": summary.arxiv_id, "status": "unjudgeable"})
            return
        invented = invented_quantities(text, abstract)
        if invented:
            self.grounding_results.append(
                {"arxiv_id": summary.arxiv_id, "status": "invented", "numbers": sorted(invented)}
            )
            return
        verdict = grounding_verdict(text, abstract)
        if verdict is None:
            self.grounding_results.append({"arxiv_id": summary.arxiv_id, "status": "unjudgeable"})
        elif verdict[0]:
            self.grounding_results.append({"arxiv_id": summary.arxiv_id, "status": "grounded", "score": round(verdict[1], 3)})
        else:
            self.grounding_results.append({"arxiv_id": summary.arxiv_id, "status": "ungrounded", "score": round(verdict[1], 3)})


# --- helpers -----------------------------------------------------------------


def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def _format_candidates(candidates: list[dict]) -> str:
    if not candidates:
        return "（空）"
    lines = []
    for candidate in candidates:
        lines.append(
            f"- {candidate.get('arxiv_id')} (score {candidate.get('score')}): {candidate.get('title')}\n"
            f"  摘要: {candidate.get('abstract', '')}"
        )
    return "\n".join(lines)


def _resolve_selected(selected_ids: list[str], candidates: list[dict]) -> list[dict]:
    by_key = {arxiv_dedupe_key(c["arxiv_id"]): c for c in candidates}
    resolved = []
    for item in selected_ids:
        candidate = by_key.get(arxiv_dedupe_key(item))
        if candidate is not None:
            resolved.append(candidate)
    return resolved


def _summary_to_dict(summary: PaperSummary) -> dict:
    return asdict(summary)


def _dict_to_summary(data: dict) -> PaperSummary:
    return PaperSummary(**data)
