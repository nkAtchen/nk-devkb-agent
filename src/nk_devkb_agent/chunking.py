from __future__ import annotations

import hashlib
import re

from .models import DocumentChunk, MarkdownDocument
from .store import tokenize


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


class MarkdownChunker:
    def __init__(self, max_chars: int = 1600) -> None:
        self.max_chars = max_chars

    def chunk(self, document: MarkdownDocument) -> list[DocumentChunk]:
        sections = self._sections(document.text)
        chunks: list[DocumentChunk] = []
        for heading_path, section_text in sections:
            for part in self._split_text(section_text):
                if not part.strip():
                    continue
                position = len(chunks)
                text_hash = hashlib.sha256(part.encode("utf-8")).hexdigest()
                chunks.append(
                    DocumentChunk(
                        heading_path=heading_path or [document.title],
                        position=position,
                        text=part,
                        text_hash=text_hash,
                        token_count=len(tokenize(part)),
                    )
                )
        return chunks

    def _sections(self, text: str) -> list[tuple[list[str], str]]:
        current_path: list[str] = []
        current_lines: list[str] = []
        sections: list[tuple[list[str], str]] = []

        def flush() -> None:
            content = "\n".join(current_lines).strip()
            if content:
                sections.append((list(current_path), content))

        in_fence = False
        for line in text.splitlines():
            if line.strip().startswith("```"):
                in_fence = not in_fence
                current_lines.append(line)
                continue
            match = None if in_fence else HEADING_RE.match(line)
            if match:
                flush()
                level = len(match.group(1))
                title = match.group(2).strip()
                current_path[:] = current_path[: level - 1]
                current_path.append(title)
                current_lines[:] = [line]
            else:
                current_lines.append(line)
        flush()
        return sections

    def _split_text(self, text: str) -> list[str]:
        if len(text) <= self.max_chars:
            return [text.strip()]

        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if not current:
                current = paragraph
            elif len(current) + len(paragraph) + 2 <= self.max_chars:
                current = f"{current}\n\n{paragraph}"
            else:
                chunks.extend(self._hard_split(current))
                current = paragraph
        if current:
            chunks.extend(self._hard_split(current))
        return chunks

    def _hard_split(self, text: str) -> list[str]:
        if len(text) <= self.max_chars:
            return [text.strip()]
        return [text[index : index + self.max_chars].strip() for index in range(0, len(text), self.max_chars)]
