from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

from .models import MarkdownDocument


HTML_TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


class UnsupportedDocumentType(ValueError):
    pass


class DocumentConverter:
    def convert(self, path: Path | str) -> MarkdownDocument:
        source_path = Path(path)
        suffix = source_path.suffix.lower()
        if suffix in {".md", ".markdown", ".txt"}:
            text = source_path.read_text(encoding="utf-8")
        elif suffix == ".json":
            text = self._json_to_markdown(json.loads(source_path.read_text(encoding="utf-8")))
        elif suffix in {".html", ".htm"}:
            text = self._html_to_markdown(source_path.read_text(encoding="utf-8"))
        elif suffix in {".pdf", ".docx"}:
            text = self._markitdown_or_error(source_path)
        else:
            raise UnsupportedDocumentType(f"Unsupported document type: {suffix or '<none>'}")
        normalized = text.strip() + "\n"
        return MarkdownDocument(
            source_path=source_path,
            title=source_path.name,
            text=normalized,
            content_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        )

    def _json_to_markdown(self, data: Any) -> str:
        lines = ["# JSON Document", ""]
        for path, value in self._flatten_json(data, "$"):
            lines.append(f"## {path}")
            lines.append("")
            lines.append(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value))
            lines.append("")
        return "\n".join(lines)

    def _flatten_json(self, value: Any, path: str) -> list[tuple[str, Any]]:
        if isinstance(value, dict):
            rows: list[tuple[str, Any]] = []
            for key, child in value.items():
                rows.extend(self._flatten_json(child, f"{path}.{key}"))
            return rows
        if isinstance(value, list):
            rows = []
            for index, child in enumerate(value):
                rows.extend(self._flatten_json(child, f"{path}[{index}]"))
            return rows
        return [(path, value)]

    def _html_to_markdown(self, raw: str) -> str:
        text = SCRIPT_STYLE_RE.sub("", raw)
        text = re.sub(r"</h([1-6])>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<h1[^>]*>", "\n# ", text, flags=re.IGNORECASE)
        text = re.sub(r"<h2[^>]*>", "\n## ", text, flags=re.IGNORECASE)
        text = re.sub(r"<h3[^>]*>", "\n### ", text, flags=re.IGNORECASE)
        text = re.sub(r"<h[4-6][^>]*>", "\n#### ", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>|<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = HTML_TAG_RE.sub("", text)
        text = html.unescape(text)
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    def _markitdown_or_error(self, source_path: Path) -> str:
        try:
            from markitdown import MarkItDown  # type: ignore
        except ImportError as exc:
            raise UnsupportedDocumentType(
                f"{source_path.suffix} conversion requires Microsoft MarkItDown to be installed"
            ) from exc
        result = MarkItDown().convert(str(source_path))
        return str(result.text_content)
