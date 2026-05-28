from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .models import ChunkRecord, CollectionSchedule, SearchResult, SourceRecord


WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for token in WORD_RE.findall(text):
        lowered = token.lower()
        tokens.append(lowered)
        cjk_chars = [char for char in lowered if "\u4e00" <= char <= "\u9fff"]
        if len(cjk_chars) >= 2:
            cjk = "".join(cjk_chars)
            tokens.extend(cjk[index : index + 2] for index in range(len(cjk) - 1))
            tokens.extend(cjk[index : index + 3] for index in range(len(cjk) - 2))
    return tokens


class KnowledgeStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists namespaces (
                    namespace text primary key,
                    root_dir text not null,
                    created_at text not null default current_timestamp
                );

                create table if not exists sources (
                    source_id text primary key,
                    namespace text not null,
                    kind text not null,
                    locator text not null,
                    title text not null,
                    status text not null,
                    content_hash text not null,
                    last_ingested_at text not null default current_timestamp,
                    error_message text not null default '',
                    unique(namespace, locator)
                );

                create table if not exists chunks (
                    chunk_id text primary key,
                    namespace text not null,
                    source_id text not null,
                    heading_path_json text not null,
                    position integer not null,
                    chunk_text text not null,
                    text_hash text not null,
                    token_count integer not null,
                    created_at text not null default current_timestamp,
                    unique(namespace, source_id, position)
                );

                create table if not exists collection_schedules (
                    schedule_id text primary key,
                    namespace text not null,
                    cron_expr text not null,
                    timezone text not null,
                    enabled integer not null
                );

                create table if not exists collection_runs (
                    collection_run_id text primary key,
                    schedule_id text not null,
                    namespace text not null,
                    started_at text not null default current_timestamp,
                    finished_at text,
                    status text not null,
                    run_summary text not null default '',
                    error_message text not null default ''
                );
                """
            )

    def upsert_namespace(self, namespace: str, root_dir: Path | str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into namespaces(namespace, root_dir)
                values(?, ?)
                on conflict(namespace) do update set root_dir = excluded.root_dir
                """,
                (namespace, str(root_dir)),
            )

    def upsert_source(
        self,
        *,
        namespace: str,
        kind: str,
        locator: str,
        title: str,
        status: str,
        content_hash: str,
    ) -> str:
        source_id = f"{namespace}:{kind}:{locator}"
        with self.connect() as conn:
            conn.execute(
                """
                insert into sources(source_id, namespace, kind, locator, title, status, content_hash)
                values(?, ?, ?, ?, ?, ?, ?)
                on conflict(namespace, locator) do update set
                    title = excluded.title,
                    status = excluded.status,
                    content_hash = excluded.content_hash,
                    last_ingested_at = current_timestamp,
                    error_message = ''
                """,
                (source_id, namespace, kind, locator, title, status, content_hash),
            )
            row = conn.execute(
                "select source_id from sources where namespace = ? and locator = ?",
                (namespace, locator),
            ).fetchone()
            return str(row["source_id"])

    def delete_chunks_for_source(self, namespace: str, source_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "delete from chunks where namespace = ? and source_id = ?",
                (namespace, source_id),
            )

    def upsert_chunk(
        self,
        *,
        namespace: str,
        source_id: str,
        heading_path: str | list[str],
        position: int,
        text: str,
        text_hash: str,
        token_count: int,
    ) -> str:
        path = [heading_path] if isinstance(heading_path, str) else heading_path
        chunk_id = f"{source_id}:{position}:{text_hash}"
        with self.connect() as conn:
            conn.execute(
                """
                insert into chunks(
                    chunk_id, namespace, source_id, heading_path_json, position,
                    chunk_text, text_hash, token_count
                )
                values(?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(namespace, source_id, position) do update set
                    chunk_id = excluded.chunk_id,
                    heading_path_json = excluded.heading_path_json,
                    chunk_text = excluded.chunk_text,
                    text_hash = excluded.text_hash,
                    token_count = excluded.token_count,
                    created_at = current_timestamp
                """,
                (
                    chunk_id,
                    namespace,
                    source_id,
                    json.dumps(path, ensure_ascii=False),
                    position,
                    text,
                    text_hash,
                    token_count,
                ),
            )
            return chunk_id

    def list_sources(self, namespace: str) -> list[SourceRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select source_id, namespace, kind, locator, title, status, content_hash
                from sources
                where namespace = ?
                order by title
                """,
                (namespace,),
            ).fetchall()
        return [
            SourceRecord(
                source_id=str(row["source_id"]),
                namespace=str(row["namespace"]),
                kind=str(row["kind"]),
                locator=str(row["locator"]),
                title=str(row["title"]),
                status=str(row["status"]),
                content_hash=str(row["content_hash"]),
            )
            for row in rows
        ]

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[ChunkRecord]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                select chunk_id, namespace, source_id, heading_path_json, position,
                       chunk_text, text_hash, token_count
                from chunks
                where chunk_id in ({placeholders})
                """,
                chunk_ids,
            ).fetchall()
        by_id = {str(row["chunk_id"]): row for row in rows}
        return [self._chunk_from_row(by_id[chunk_id]) for chunk_id in chunk_ids if chunk_id in by_id]

    def all_chunks(self, namespace: str) -> list[SearchResult]:
        return self.search_chunks(namespace, "", top_k=10_000)

    def chunks_for_source_target(self, namespace: str, target: str) -> list[SearchResult]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select c.chunk_id, c.source_id, c.heading_path_json, c.chunk_text,
                       s.title, s.locator
                from chunks c
                join sources s on s.source_id = c.source_id
                where c.namespace = ?
                  and (s.source_id = ? or s.title = ? or s.locator = ?)
                order by c.position
                """,
                (namespace, target, target, target),
            ).fetchall()
        return [
            SearchResult(
                chunk_id=str(row["chunk_id"]),
                source_id=str(row["source_id"]),
                title=str(row["title"]),
                locator=str(row["locator"]),
                heading_path=list(json.loads(str(row["heading_path_json"]))),
                text=str(row["chunk_text"]),
                score=1.0,
            )
            for row in rows
        ]

    def search_chunks(self, namespace: str, query: str, top_k: int) -> list[SearchResult]:
        query_terms = tokenize(query)
        with self.connect() as conn:
            rows = conn.execute(
                """
                select c.chunk_id, c.source_id, c.heading_path_json, c.chunk_text,
                       s.title, s.locator
                from chunks c
                join sources s on s.source_id = c.source_id
                where c.namespace = ?
                """,
                (namespace,),
            ).fetchall()

        results: list[SearchResult] = []
        for row in rows:
            text = str(row["chunk_text"])
            if query_terms:
                haystack = tokenize(text + " " + str(row["title"]) + " " + str(row["heading_path_json"]))
                score = sum(1 for term in query_terms if term in haystack)
                if score <= 0:
                    continue
            else:
                score = 1
            results.append(
                SearchResult(
                    chunk_id=str(row["chunk_id"]),
                    source_id=str(row["source_id"]),
                    title=str(row["title"]),
                    locator=str(row["locator"]),
                    heading_path=list(json.loads(str(row["heading_path_json"]))),
                    text=text,
                    score=float(score),
                )
            )

        return sorted(results, key=lambda item: (-item.score, item.title, item.chunk_id))[:top_k]

    def save_schedule(self, schedule: CollectionSchedule) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into collection_schedules(schedule_id, namespace, cron_expr, timezone, enabled)
                values(?, ?, ?, ?, ?)
                on conflict(schedule_id) do update set
                    cron_expr = excluded.cron_expr,
                    timezone = excluded.timezone,
                    enabled = excluded.enabled
                """,
                (
                    schedule.schedule_id,
                    schedule.namespace,
                    schedule.cron_expr,
                    schedule.timezone,
                    int(schedule.enabled),
                ),
            )

    def list_schedules(self, namespace: str) -> list[CollectionSchedule]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select schedule_id, namespace, cron_expr, timezone, enabled
                from collection_schedules
                where namespace = ?
                order by schedule_id
                """,
                (namespace,),
            ).fetchall()
        return [
            CollectionSchedule(
                schedule_id=str(row["schedule_id"]),
                namespace=str(row["namespace"]),
                cron_expr=str(row["cron_expr"]),
                timezone=str(row["timezone"]),
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]

    def _chunk_from_row(self, row: sqlite3.Row) -> ChunkRecord:
        return ChunkRecord(
            chunk_id=str(row["chunk_id"]),
            namespace=str(row["namespace"]),
            source_id=str(row["source_id"]),
            heading_path=list(json.loads(str(row["heading_path_json"]))),
            position=int(row["position"]),
            text=str(row["chunk_text"]),
            text_hash=str(row["text_hash"]),
            token_count=int(row["token_count"]),
        )
