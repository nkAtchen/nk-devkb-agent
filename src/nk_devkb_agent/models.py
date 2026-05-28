from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    namespace: str
    kind: str
    locator: str
    title: str
    status: str
    content_hash: str


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    namespace: str
    source_id: str
    heading_path: list[str]
    position: int
    text: str
    text_hash: str
    token_count: int


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    source_id: str
    title: str
    locator: str
    heading_path: list[str]
    text: str
    score: float


@dataclass(frozen=True)
class MarkdownDocument:
    source_path: Path
    title: str
    text: str
    content_hash: str


@dataclass(frozen=True)
class DocumentChunk:
    heading_path: list[str]
    position: int
    text: str
    text_hash: str
    token_count: int


@dataclass(frozen=True)
class ReflectionResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    suggested_action: str = "present"


@dataclass(frozen=True)
class Answer:
    text: str
    used_rag: bool
    no_rag_context: bool
    reflection: ReflectionResult
    citations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CollectionSchedule:
    schedule_id: str
    namespace: str
    cron_expr: str
    timezone: str
    enabled: bool
