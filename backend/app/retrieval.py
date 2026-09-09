"""Hybrid retrieval: lexical + vector, fused with Reciprocal Rank Fusion.

Legal queries are half semantic ("what is res judicata") and half lexical
("Section 11 CPC", "Satyadhyan Ghosal"). Pure vector search is unreliable on exact
section numbers and case names; pure keyword search misses paraphrase. So both run and
their rankings are fused.

Three stages:

  1. SECTION PIN - if the query names a section ("s. 35", "Section 173 BNSS"), that
     provision is fetched directly and pinned to the top. A student asking for a section
     wants THAT section, not the most semantically similar paragraph to it.
  2. HYBRID - Postgres full-text (ts_rank_cd) and pgvector cosine, top-30 each.
  3. RRF - score = sum(1 / (60 + rank)). Rank-based, so it needs no score calibration
     between two systems whose scores are not comparable.

Everything served goes through the licence gate in licence.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.app.config import settings
from backend.app.db import connection
from backend.app.licence import serve_text

RRF_K = 60
CANDIDATES = 30

# "Section 11", "s. 41A", "sec 173", "u/s 35"
SECTION_RE = re.compile(
    r"(?:section|sec\.?|s\.|u/s)\s*([0-9]{1,3}[A-Z]{0,2})\b",
    re.IGNORECASE,
)
# A bare act abbreviation mentioned alongside, e.g. "Section 11 CPC"
ACT_HINT_RE = re.compile(
    r"\b(cpc|crpc|bnss|bns|bsa|pocso|jj|id act|osh|ir code)\b", re.IGNORECASE
)

_ACT_SLUG_HINTS = {
    "cpc": "code-of-civil-procedure",
    "crpc": "code-of-criminal-procedure",
    "bnss": "bharatiya-nagarik-suraksha-sanhita",
    "bns": "bharatiya-nyaya-sanhita",
    "bsa": "bharatiya-sakshya-adhiniyam",
    "pocso": "protection-of-children",
    "jj": "juvenile-justice",
    "osh": "occupational-safety",
    "ir code": "industrial-relations-code",
}


@dataclass
class Hit:
    chunk_id: int
    text: str
    heading: str | None
    citation: str
    document_title: str
    doc_type: str
    licence: str
    truncated: bool
    score: float
    pinned: bool = False
    matched_by: list[str] = field(default_factory=list)


def parse_section_reference(query: str) -> tuple[str | None, str | None]:
    """Return (section_no, act_slug_fragment) if the query names a section."""
    m = SECTION_RE.search(query)
    if not m:
        return None, None
    act = ACT_HINT_RE.search(query)
    hint = _ACT_SLUG_HINTS.get(act.group(1).lower()) if act else None
    return m.group(1).upper(), hint


def _rrf(rank: int) -> float:
    return 1.0 / (RRF_K + rank)


async def _lexical(conn, query: str, subject: str | None) -> list[int]:
    rows = await conn.fetch(
        """
        SELECT c.id
        FROM chunk c
        JOIN document d ON d.id = c.document_id
        LEFT JOIN subject s ON s.id = d.subject_id
        WHERE c.tsv @@ websearch_to_tsquery('english', $1)
          AND ($2::text IS NULL OR s.code = $2)
        ORDER BY ts_rank_cd(c.tsv, websearch_to_tsquery('english', $1)) DESC
        LIMIT $3
        """,
        query,
        subject,
        CANDIDATES,
    )
    return [r["id"] for r in rows]


async def _vector(conn, embedding: str | None, subject: str | None) -> list[int]:
    if embedding is None:
        return []
    rows = await conn.fetch(
        """
        SELECT c.id
        FROM chunk c
        JOIN document d ON d.id = c.document_id
        LEFT JOIN subject s ON s.id = d.subject_id
        WHERE c.embedding IS NOT NULL
          AND ($2::text IS NULL OR s.code = $2)
        ORDER BY c.embedding <=> $1::vector
        LIMIT $3
        """,
        embedding,
        subject,
        CANDIDATES,
    )
    return [r["id"] for r in rows]


async def _pinned_section(conn, section_no: str, act_hint: str | None) -> int | None:
    row = await conn.fetchrow(
        """
        SELECT c.id
        FROM provision p
        JOIN act a ON a.id = p.act_id
        JOIN chunk c ON c.provision_id = p.id
        WHERE upper(p.section_no) = upper($1)
          AND ($2::text IS NULL OR a.slug LIKE $2 || '%')
        ORDER BY length(p.text) DESC
        LIMIT 1
        """,
        section_no,
        act_hint,
    )
    return row["id"] if row else None


async def _hydrate(conn, ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT c.id, c.text, c.heading,
               d.title AS document_title, d.doc_type::text AS doc_type,
               d.licence::text AS licence,
               a.short_title, a.year, p.section_no,
               cl.name AS case_name, cl.neutral_citation
        FROM chunk c
        JOIN document d ON d.id = c.document_id
        LEFT JOIN provision p ON p.id = c.provision_id
        LEFT JOIN act a ON a.id = p.act_id
        LEFT JOIN case_law cl ON cl.id = c.case_id
        WHERE c.id = ANY($1::bigint[])
        """,
        ids,
    )
    return {r["id"]: dict(r) for r in rows}


def _citation(row: dict) -> str:
    if row.get("section_no") and row.get("short_title"):
        year = f", {row['year']}" if row.get("year") else ""
        return f"Section {row['section_no']}, {row['short_title']}{year}"
    if row.get("case_name"):
        cite = row.get("neutral_citation")
        return f"{row['case_name']} {cite}" if cite else row["case_name"]
    return row.get("document_title") or "source"


async def search(query: str, *, subject: str | None = None, limit: int = 10) -> list[Hit]:
    """Hybrid search. Returns licence-gated hits, best first."""
    embedding = None
    if settings.enable_vector_search:
        try:
            from ingest.embed import embed_query, to_pgvector

            embedding = to_pgvector(embed_query(query))
        except Exception:
            # Vector search is an enhancement, not a dependency. If the embedding model
            # is unavailable or chunks are not embedded yet, lexical search still
            # answers rather than the request failing.
            embedding = None

    async with connection() as conn:
        lexical_ids = await _lexical(conn, query, subject)
        vector_ids = await _vector(conn, embedding, subject)

        scores: dict[int, float] = {}
        matched: dict[int, list[str]] = {}
        for rank, cid in enumerate(lexical_ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + _rrf(rank)
            matched.setdefault(cid, []).append("keyword")
        for rank, cid in enumerate(vector_ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + _rrf(rank)
            matched.setdefault(cid, []).append("semantic")

        section_no, act_hint = parse_section_reference(query)
        pinned_id = await _pinned_section(conn, section_no, act_hint) if section_no else None
        if pinned_id is not None:
            # Above any fused score, which cannot exceed 2/(RRF_K+1).
            scores[pinned_id] = 10.0
            matched.setdefault(pinned_id, []).insert(0, "section reference")

        ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        rows = await _hydrate(conn, [cid for cid, _ in ordered])

    hits: list[Hit] = []
    for cid, score in ordered:
        row = rows.get(cid)
        if row is None:
            continue
        text, truncated = serve_text(row["text"], row["licence"])
        hits.append(
            Hit(
                chunk_id=cid,
                text=text,
                heading=row["heading"],
                citation=_citation(row),
                document_title=row["document_title"],
                doc_type=row["doc_type"],
                licence=row["licence"],
                truncated=truncated,
                score=round(score, 5),
                pinned=cid == pinned_id,
                matched_by=matched.get(cid, []),
            )
        )
    return hits
