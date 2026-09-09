"""FastAPI app.

Phase 1 surface only: browse the corpus and confirm it loaded correctly. Search arrives
in Phase 2, AI answering in Phase 3. Every response that carries chunk text goes through
the licence gate in backend/app/licence.py.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.db import close_pool, connection, get_pool
from backend.app.licence import serve_text
from backend.app.retrieval import search as hybrid_search


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()


app = FastAPI(title="LLB Sutra", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    async with connection() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


@app.get("/stats")
async def stats() -> dict:
    """Corpus size. The fastest way to see whether ingestion actually worked."""
    async with connection() as conn:
        rows = await conn.fetch(
            """
            SELECT 'documents' AS kind, count(*) FROM document
            UNION ALL SELECT 'provisions', count(*) FROM provision
            UNION ALL SELECT 'chunks', count(*) FROM chunk
            UNION ALL SELECT 'chunks_embedded', count(*) FROM chunk WHERE embedding IS NOT NULL
            UNION ALL SELECT 'cases', count(*) FROM case_law
            UNION ALL SELECT 'pyqs', count(*) FROM pyq
            UNION ALL SELECT 'subjects', count(*) FROM subject
            """
        )
    return {r["kind"]: r["count"] for r in rows}


@app.get("/subjects")
async def subjects() -> list[dict]:
    async with connection() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.code, s.name, s.slug, s.semester,
                   count(DISTINCT d.id) AS documents
            FROM subject s
            LEFT JOIN document d ON d.subject_id = s.id
            GROUP BY s.id
            ORDER BY s.code
            """
        )
    return [dict(r) for r in rows]


@app.get("/acts")
async def acts() -> list[dict]:
    async with connection() as conn:
        rows = await conn.fetch(
            """
            SELECT a.id, a.short_title, a.year, a.slug, count(p.id) AS sections
            FROM act a
            LEFT JOIN provision p ON p.act_id = a.id
            GROUP BY a.id
            ORDER BY a.short_title
            """
        )
    return [dict(r) for r in rows]


@app.get("/acts/{slug}/sections")
async def sections(slug: str) -> list[dict]:
    async with connection() as conn:
        rows = await conn.fetch(
            """
            SELECT p.section_no, p.marginal_note
            FROM provision p
            JOIN act a ON a.id = p.act_id
            WHERE a.slug = $1
            ORDER BY p.ord
            """,
            slug,
        )
    if not rows:
        raise HTTPException(404, f"no act with slug {slug!r}, or it has no parsed sections")
    return [dict(r) for r in rows]


@app.get("/acts/{slug}/sections/{section_no}")
async def section(slug: str, section_no: str) -> dict:
    """Statutory text, served VERBATIM. Bare acts are govt-public, so never truncated."""
    async with connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.section_no, p.marginal_note, p.text, a.short_title, a.year,
                   coalesce(d.licence::text, 'govt-public') AS licence
            FROM provision p
            JOIN act a ON a.id = p.act_id
            LEFT JOIN document d ON d.act_id = a.id
            WHERE a.slug = $1 AND upper(p.section_no) = upper($2)
            LIMIT 1
            """,
            slug,
            section_no,
        )
    if row is None:
        raise HTTPException(404, f"{slug} has no section {section_no}")

    text, truncated = serve_text(row["text"], row["licence"])
    return {
        "act": row["short_title"],
        "year": row["year"],
        "section_no": row["section_no"],
        "marginal_note": row["marginal_note"],
        "text": text,
        "truncated": truncated,
        "citation": f"Section {row['section_no']}, {row['short_title']}, {row['year']}",
    }


@app.get("/syllabus")
async def syllabus(subject: str | None = None) -> list[dict]:
    """The Semester V syllabus: subjects -> modules -> topics.

    Parsed from the MU revision circular (BNSS paper) and the programme syllabus
    (CPC, Labour II, PIL). Modules carry the count of questions asked from them, so a
    student can see which parts of the syllabus the examiners actually favour.
    """
    async with connection() as conn:
        rows = await conn.fetch(
            """
            SELECT s.code, s.name, s.slug, s.semester,
                   m.id AS module_id, m.number AS module_number, m.title AS module_title,
                   t.id AS topic_id, t.title AS topic_title, t.slug AS topic_slug
            FROM subject s
            LEFT JOIN module m ON m.subject_id = s.id
            LEFT JOIN topic t  ON t.module_id = m.id
            WHERE ($1::text IS NULL OR s.code = $1)
            ORDER BY s.code, m.number, t.id
            """,
            subject,
        )

    out: dict[str, dict] = {}
    for r in rows:
        subj = out.setdefault(
            r["code"],
            {
                "code": r["code"],
                "name": r["name"],
                "slug": r["slug"],
                "semester": r["semester"],
                "modules": {},
            },
        )
        if r["module_id"] is None:
            continue
        mod = subj["modules"].setdefault(
            r["module_id"],
            {"number": r["module_number"], "title": r["module_title"], "topics": []},
        )
        if r["topic_id"] is not None:
            mod["topics"].append({"title": r["topic_title"], "slug": r["topic_slug"]})

    return [
        {**s, "modules": sorted(s["modules"].values(), key=lambda m: m["number"])}
        for s in out.values()
    ]


@app.get("/search")
async def search(q: str, subject: str | None = None, limit: int = 10) -> dict:
    """Hybrid keyword + semantic search over the whole corpus."""
    if not q.strip():
        raise HTTPException(400, "q is required")
    hits = await hybrid_search(q, subject=subject, limit=min(limit, 50))
    return {
        "query": q,
        "subject": subject,
        "count": len(hits),
        "results": [
            {
                "chunk_id": h.chunk_id,
                "heading": h.heading,
                "text": h.text,
                "citation": h.citation,
                "source": h.document_title,
                "doc_type": h.doc_type,
                "truncated": h.truncated,
                "matched_by": h.matched_by,
                "pinned": h.pinned,
                "score": h.score,
            }
            for h in hits
        ],
    }


@app.get("/pyq")
async def pyq(subject: str | None = None, year: int | None = None, limit: int = 100) -> list[dict]:
    """Previous-year questions, newest first."""
    async with connection() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, s.code AS subject, p.year, p.exam, p.marks,
                   p.question_no, p.question_text
            FROM pyq p JOIN subject s ON s.id = p.subject_id
            WHERE ($1::text IS NULL OR s.code = $1)
              AND ($2::int  IS NULL OR p.year = $2)
            ORDER BY p.year DESC, p.exam, p.question_no
            LIMIT $3
            """,
            subject,
            year,
            min(limit, 500),
        )
    return [dict(r) for r in rows]


@app.get("/pyq/topics")
async def pyq_topics(subject: str | None = None) -> list[dict]:
    """Topic frequency across question papers.

    This is the feature no competitor offers: which topics your examiners actually
    repeat, counted from your own papers rather than guessed.

    Topic patterns live here rather than in a table because they are still being
    tuned against real papers; they move into `topic.keywords` once the syllabus
    modules are parsed.
    """
    patterns = [
        ("Res judicata", r"res.?judicata"),
        ("Summons", r"summons"),
        ("Execution of decree", r"execution"),
        ("Limitation / condonation of delay", r"limitation|condonation|delay"),
        ("Plaint / pleadings", r"plaint|pleading"),
        ("Jurisdiction", r"jurisdiction"),
        ("Arrest", r"arrest"),
        ("Bail", r"bail"),
        ("Anticipatory bail", r"anticipatory"),
        ("FIR / information to police", r"F\.?I\.?R|information to|first information"),
        ("Charge", r"charge"),
        ("Juvenile justice", r"juvenile|child in conflict"),
        ("POCSO", r"pocso"),
        ("Gig worker / social security", r"gig|social security"),
        ("Gratuity", r"gratuity"),
        ("Strike / lockout", r"strike|lock.?out"),
        ("Trade union", r"trade union"),
        ("Treaty", r"treaty|treaties"),
        ("Recognition of states", r"recognition"),
        ("Extradition", r"extradition"),
        ("Asylum", r"asylum"),
        ("State jurisdiction / sovereignty", r"sovereign"),
    ]
    async with connection() as conn:
        rows = await conn.fetch(
            """
            WITH t(topic, pat) AS (
                SELECT * FROM unnest($1::text[], $2::text[])
            )
            SELECT t.topic,
                   count(*) AS times_asked,
                   count(DISTINCT p.exam) AS in_papers,
                   min(p.year) AS first_seen,
                   max(p.year) AS last_seen,
                   array_agg(DISTINCT s.code) AS subjects
            FROM t
            JOIN pyq p ON p.question_text ~* t.pat
            JOIN subject s ON s.id = p.subject_id
            WHERE ($3::text IS NULL OR s.code = $3)
            GROUP BY t.topic
            ORDER BY times_asked DESC
            """,
            [p[0] for p in patterns],
            [p[1] for p in patterns],
            subject,
        )
    return [dict(r) for r in rows]


# The single-page frontend. Mounted last so it never shadows an API route.
_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(str(_FRONTEND / "index.html"))
