from nk_devkb_agent.chunking import MarkdownChunker
from nk_devkb_agent.documents import DocumentConverter


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


def test_html_conversion_strips_tags(tmp_path):
    path = tmp_path / "page.html"
    path.write_text("<h1>Title</h1><p>Hello <strong>world</strong>.</p>", encoding="utf-8")

    doc = DocumentConverter().convert(path)

    assert "Title" in doc.text
    assert "Hello world." in doc.text
    assert "<strong>" not in doc.text


def test_chunker_ignores_headings_inside_fenced_code_blocks(tmp_path):
    path = tmp_path / "design.md"
    path.write_text(
        "# Real Title\n\n"
        "```text\n"
        "# Not A Heading\n"
        "## Also Not A Heading\n"
        "```\n\n"
        "## Real Section\n"
        "Actual content.",
        encoding="utf-8",
    )

    doc = DocumentConverter().convert(path)
    chunks = MarkdownChunker(max_chars=200).chunk(doc)

    assert chunks[-1].heading_path == ["Real Title", "Real Section"]
