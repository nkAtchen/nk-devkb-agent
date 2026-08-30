from nk_devkb_agent.pipeline import create_rag_pipeline


class CapturingLLM:
    def __init__(self):
        self.last_question = ""
        self.last_evidence = []

    def synthesize_with_evidence(self, question, evidence):
        self.last_question = question
        self.last_evidence = evidence
        return "LLM answer with RAG context"

    def synthesize_without_evidence(self, user_prompt, default_system_prompt):
        self.last_question = user_prompt
        self.last_evidence = []
        return "no_rag_context\nLLM fallback"

    def summarize(self, title, texts):
        return f"Summary for {title}: {' '.join(texts)}"


def test_ask_uses_evidence_when_available(tmp_path):
    tool = create_rag_pipeline(db_path=tmp_path / "kb.sqlite", namespace="demo")
    doc = tmp_path / "guide.md"
    doc.write_text("# Architecture\n\nThe planner splits questions before retrieval.", encoding="utf-8")
    tool.ingest_file(doc, namespace="demo")

    answer = tool.ask("How does the system answer questions?", namespace="demo")

    assert answer.used_rag is True
    assert answer.no_rag_context is False
    assert answer.reflection.passed is True
    assert answer.citations
    assert "planner" in answer.text.lower()


def test_ask_falls_back_to_default_prompt_when_no_hits(tmp_path):
    tool = create_rag_pipeline(db_path=tmp_path / "kb.sqlite", namespace="demo")

    answer = tool.ask("Explain the upload flow.", namespace="demo")

    assert answer.used_rag is False
    assert answer.no_rag_context is True
    assert answer.reflection.passed is True
    assert "no_rag_context" in answer.text


def test_ask_retrieves_chinese_short_query(tmp_path):
    tool = create_rag_pipeline(db_path=tmp_path / "kb.sqlite", namespace="demo")
    doc = tmp_path / "guide.md"
    doc.write_text("# 问答链路\n\n系统问答链路先检索知识库，再进行反思。", encoding="utf-8")
    tool.ingest_file(doc, namespace="demo")

    answer = tool.ask("系统问答链路是什么", namespace="demo")

    assert answer.used_rag is True
    assert "知识库" in answer.text


def test_search_prefers_heading_matches_for_chinese_query(tmp_path):
    tool = create_rag_pipeline(db_path=tmp_path / "kb.sqlite", namespace="demo")
    doc = tmp_path / "guide.md"
    doc.write_text(
        "# LLM Provider\n\nLLM 用于多步问答中的 reflection。\n\n"
        "# 问答链路\n\n系统问答链路先检索知识库，再进行反思。",
        encoding="utf-8",
    )
    tool.ingest_file(doc, namespace="demo")

    results = tool.search("系统问答链路是什么", namespace="demo")

    assert results[0].heading_path == ["问答链路"]


def test_ask_sends_retrieved_rag_context_to_llm(tmp_path):
    llm = CapturingLLM()
    tool = create_rag_pipeline(db_path=tmp_path / "kb.sqlite", namespace="demo", llm=llm)
    doc = tmp_path / "guide.md"
    doc.write_text("# RAG\n\nRetrieved context should be sent to the LLM.", encoding="utf-8")
    tool.ingest_file(doc, namespace="demo")

    answer = tool.ask("How should retrieved context be used?", namespace="demo")

    assert answer.used_rag is True
    assert llm.last_question == "How should retrieved context be used?"
    assert any("Retrieved context" in item.text for item in llm.last_evidence)
    assert answer.text == "LLM answer with RAG context"
