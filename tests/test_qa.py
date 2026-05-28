from nk_devkb_agent.pipeline import create_rag_pipeline


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
