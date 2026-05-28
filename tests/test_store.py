from nk_devkb_agent.store import KnowledgeStore


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
    assert sources[0].title == "notes.md"
    assert chunks[0].chunk_id == chunk_id
    assert chunks[0].score > 0
