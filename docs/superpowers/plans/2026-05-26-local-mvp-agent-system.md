# Local MVP Agent System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable local-only CLI knowledge-base agent that supports init, ingest, search, ask, summarize, sources, refresh, and schedule commands while keeping the LLM/embedding/vector-store boundaries replaceable for later cloud integration.

**Architecture:** Use a `src/`-layout Python package with only standard-library runtime dependencies. Persist namespaces, sources, chunks, schedules, and runs in SQLite; convert local documents into normalized Markdown/text; chunk and retrieve with deterministic local logic; route ask requests through a mockable LLM/reflection layer so the later Qdrant/OpenAI/DeepSeek adapters can slot in without changing the CLI or data model.

**Tech Stack:** Python 3.11+, `sqlite3`, `argparse`, `dataclasses`, `hashlib`, `json`, `pathlib`, `pytest`.

---

### Task 1: Package scaffold and SQLite store

**Files:**
- Create: `pyproject.toml`
- Create: `src/nk_devkb_agent/__init__.py`
- Create: `src/nk_devkb_agent/models.py`
- Create: `src/nk_devkb_agent/store.py`
- Create: `tests/conftest.py`
- Create: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
def test_store_round_trip(tmp_path):
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    store.ensure_schema()
    store.upsert_namespace("demo", root_dir=tmp_path)

    source_id = store.upsert_source(
        namespace="demo",
        kind="local_file",
        locator=str(tmp_path / "notes.md"),
        title="notes.md",
        status="ready",
        content_hash="hash-1",
    )
    chunk_id = store.upsert_chunk(
        namespace="demo",
        source_id=source_id,
        heading_path="# Intro",
        position=0,
        text="hello architecture",
        text_hash="chunk-1",
        token_count=2,
    )

    sources = store.list_sources("demo")
    chunks = store.search_chunks("demo", "architecture", top_k=5)

    assert sources[0].source_id == source_id
    assert chunks[0].chunk_id == chunk_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store.py -q`
Expected: fail because `KnowledgeStore` and the dataclasses do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement `KnowledgeStore`, schema creation, namespace/source/chunk upserts, list/query methods, and dataclasses for source/chunk/search results.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_store.py -q`
Expected: pass.

### Task 2: Document conversion and chunking

**Files:**
- Create: `src/nk_devkb_agent/documents.py`
- Create: `src/nk_devkb_agent/chunking.py`
- Create: `tests/test_documents.py`

- [ ] **Step 1: Write the failing test**

```python
def test_flatten_json_and_chunk_markdown(tmp_path):
    json_path = tmp_path / "doc.json"
    json_path.write_text('{"title":"Doc","items":[{"name":"A"}]}', encoding="utf-8")
    md_path = tmp_path / "doc.md"
    md_path.write_text("# Title\n\nParagraph one.\n\n## Details\nMore text.", encoding="utf-8")

    json_doc = DocumentConverter().convert(json_path)
    markdown_doc = DocumentConverter().convert(md_path)
    chunks = MarkdownChunker(max_chars=40).chunk(markdown_doc)

    assert "$.title" in json_doc.text
    assert "$.items[0].name" in json_doc.text
    assert chunks[0].heading_path == ["Title"]
    assert any("Details" in " / ".join(chunk.heading_path) for chunk in chunks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_documents.py -q`
Expected: fail because `DocumentConverter` and `MarkdownChunker` do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement Markdown/TXT/JSON/HTML conversion, optional MarkItDown fallback for PDF/DOCX, HTML stripping, JSON path flattening, and heading-aware chunking.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_documents.py -q`
Expected: pass.

### Task 3: Retrieval, ask flow, reflection, and summaries

**Files:**
- Create: `src/nk_devkb_agent/retrieval.py`
- Create: `src/nk_devkb_agent/llm.py`
- Create: `src/nk_devkb_agent/reflection.py`
- Create: `src/nk_devkb_agent/pipeline.py`
- Create: `tests/test_qa.py`

- [ ] **Step 1: Write the failing test**

```python
def test_ask_uses_evidence_when_available(tmp_path):
    tool = create_rag_pipeline(db_path=tmp_path / "kb.sqlite", namespace="demo")
    doc = tmp_path / "guide.md"
    doc.write_text("# Architecture\n\nThe planner splits questions before retrieval.", encoding="utf-8")
    tool.ingest_file(doc, namespace="demo")

    answer = tool.ask("How does the system answer questions?", namespace="demo")

    assert answer.used_rag is True
    assert answer.reflection.passed is True
    assert answer.citations


def test_ask_falls_back_to_default_prompt_when_no_hits(tmp_path):
    tool = create_rag_pipeline(db_path=tmp_path / "kb.sqlite", namespace="demo")

    answer = tool.ask("Explain the upload flow.", namespace="demo")

    assert answer.used_rag is False
    assert answer.no_rag_context is True
    assert answer.reflection.passed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_qa.py -q`
Expected: fail because the pipeline, retrieval, and reflection logic do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement question planning, deterministic retrieval scoring, evidence/no-evidence branching, default prompt synthesis, and reflection gating with structured pass/fail reasons.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_qa.py -q`
Expected: pass.

### Task 4: CLI commands and smoke coverage

**Files:**
- Create: `src/nk_devkb_agent/cli.py`
- Create: `src/nk_devkb_agent/__main__.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
def test_cli_init_ingest_search_and_ask(tmp_path, capsys):
    doc = tmp_path / "notes.md"
    doc.write_text("# Notes\n\nThe summary command reads stored chunks.", encoding="utf-8")

    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main(["ingest", "file", str(doc), "--root", str(tmp_path)]) == 0
    assert main(["search", "summary", "--root", str(tmp_path)]) == 0
    assert main(["ask", "What does the summary command read?", "--root", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "notes.md" in out
    assert "reflection" in out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -q`
Expected: fail because the CLI entry point does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement `argparse` subcommands for `init`, `ingest`, `ask`, `search`, `summarize`, `sources`, `refresh`, `schedule set`, `schedule list`, and `schedule run-now`, all wired to the same local pipeline.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -q`
Expected: pass.
