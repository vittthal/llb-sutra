"""Fetched/registered PDFs -> Postgres.

Idempotent: a document is keyed by the sha256 of its file, so re-running after adding
one new PDF re-processes only that PDF. Change the file and it re-processes; leave it
alone and it is skipped.

    python -m ingest.load                 # everything not yet loaded
    python -m ingest.load --only cpc-1908
    python -m ingest.load --reload cpc-1908   # drop and re-ingest one document
    python -m ingest.load --skip-embeddings   # structure only; Phase 1 needs no vectors
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from slugify import slugify

from backend.app.db import close_pool, transaction
from ingest import chunk as chunker
from ingest import parse_act
from ingest.embed import embed_documents, to_pgvector
from ingest.extract import extract
from ingest.sources import Manifest, SourceDoc, load_manifest, sha256_file

app = typer.Typer(add_completion=False)
console = Console()


async def _ensure_subjects(conn, manifest: Manifest) -> dict[str, int]:
    ids: dict[str, int] = {}
    for subject in manifest.subjects:
        row = await conn.fetchrow(
            """
            INSERT INTO subject (code, name, slug, semester)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (university, semester, code)
            DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            subject.code,
            subject.name,
            subject.slug,
            subject.semester,
        )
        ids[subject.code] = row["id"]
    return ids


async def _ensure_act(conn, doc: SourceDoc) -> int | None:
    if not doc.act:
        return None
    short_title = doc.act["short_title"]
    row = await conn.fetchrow(
        """
        INSERT INTO act (short_title, year, act_number, slug)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (slug) DO UPDATE SET short_title = EXCLUDED.short_title
        RETURNING id
        """,
        short_title,
        doc.act.get("year"),
        doc.act.get("act_number"),
        slugify(f"{short_title}-{doc.act.get('year', '')}")[:80],
    )
    return row["id"]


async def _load_one(
    conn,
    doc: SourceDoc,
    path: Path,
    subject_ids: dict[str, int],
    *,
    skip_embeddings: bool,
) -> tuple[str, int, int]:
    """Returns (status, n_provisions, n_chunks)."""
    checksum = sha256_file(path)

    existing = await conn.fetchrow("SELECT id FROM document WHERE checksum = $1", checksum)
    if existing:
        return "unchanged", 0, 0

    act_id = await _ensure_act(conn, doc)
    subject_id = subject_ids.get(doc.subject) if doc.subject else None

    doc_row = await conn.fetchrow(
        """
        INSERT INTO document
            (title, source_url, local_path, doc_type, licence, checksum, subject_id, act_id)
        VALUES ($1, $2, $3, $4::doc_type, $5::licence, $6, $7, $8)
        RETURNING id
        """,
        doc.title,
        doc.fetch[0] if doc.fetch else None,
        str(path),
        doc.doc_type,
        doc.licence,
        checksum,
        subject_id,
        act_id,
    )
    document_id = doc_row["id"]

    extracted = extract(path)
    if extracted.ocr_pages:
        console.print(f"[dim]  OCR used on {extracted.ocr_pages} page(s)[/dim]")

    chunks: list[chunker.Chunk] = []
    provision_ids: list[int | None] = []
    n_provisions = 0

    if doc.doc_type in {"bare_act", "treaty"} and act_id is not None:
        provisions = parse_act.parse(extracted.text)
        n_provisions = len(provisions)
        for prov in provisions:
            row = await conn.fetchrow(
                """
                INSERT INTO provision (act_id, section_no, marginal_note, text, ord)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (act_id, section_no)
                DO UPDATE SET text = EXCLUDED.text, marginal_note = EXCLUDED.marginal_note
                RETURNING id
                """,
                act_id,
                prov.section_no,
                prov.marginal_note,
                prov.text,
                prov.ord,
            )
            chunks.append(
                chunker.chunk_provision(
                    prov.section_no, prov.marginal_note, prov.text, len(chunks)
                )
            )
            provision_ids.append(row["id"])

    if not chunks:
        # Not an act, or the parser found no sections: fall back to document chunking.
        chunks = chunker.chunk_document(extracted.text, doc.doc_type)
        provision_ids = [None] * len(chunks)

    vectors: list[str | None] = [None] * len(chunks)
    if not skip_embeddings and chunks:
        raw = embed_documents(c.text for c in chunks)
        vectors = [to_pgvector(v) for v in raw]

    for c, provision_id, vec in zip(chunks, provision_ids, vectors, strict=True):
        await conn.execute(
            """
            INSERT INTO chunk (document_id, provision_id, ord, heading, text, n_tokens, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7::vector)
            """,
            document_id,
            provision_id,
            c.ord,
            c.heading,
            c.text,
            c.n_tokens,
            vec,
        )

    return "loaded", n_provisions, len(chunks)


async def _run(only: str | None, reload_slug: str | None, skip_embeddings: bool) -> int:
    manifest = load_manifest()
    target = reload_slug or only
    docs = [d for d in manifest.documents if not target or d.slug == target]
    if not docs:
        console.print(f"[red]no document matching {target!r}[/red]")
        return 1

    rows: list[tuple[str, str, int, int]] = []
    failures = 0

    async with transaction() as conn:
        subject_ids = await _ensure_subjects(conn, manifest)

        if reload_slug:
            await conn.execute(
                "DELETE FROM document WHERE local_path LIKE $1 OR title = $2",
                f"%{reload_slug}%",
                next((d.title for d in docs), ""),
            )

        for doc in docs:
            path = doc.resolved_path()
            if not path.exists():
                console.print(f"[yellow]missing[/yellow] {doc.slug}: {path}")
                rows.append((doc.slug, "missing file", 0, 0))
                failures += 1
                continue
            console.print(f"[bold]{doc.slug}[/bold]")
            try:
                status, n_prov, n_chunks = await _load_one(
                    conn, doc, path, subject_ids, skip_embeddings=skip_embeddings
                )
            except Exception as exc:  # keep going; one bad PDF should not stop the run
                console.print(f"[red]  failed: {type(exc).__name__}: {exc}[/red]")
                rows.append((doc.slug, f"error: {type(exc).__name__}", 0, 0))
                failures += 1
                continue
            rows.append((doc.slug, status, n_prov, n_chunks))

    table = Table(title="load")
    table.add_column("slug", style="cyan")
    table.add_column("status")
    table.add_column("provisions", justify="right")
    table.add_column("chunks", justify="right")
    for slug, status, n_prov, n_chunks in rows:
        table.add_row(slug, status, str(n_prov), str(n_chunks))
    console.print(table)

    await close_pool()
    return 1 if failures else 0


@app.command()
def main(
    only: str = typer.Option(None, "--only", help="Load a single slug."),
    reload_slug: str = typer.Option(None, "--reload", help="Drop and re-ingest a slug."),
    skip_embeddings: bool = typer.Option(
        False, "--skip-embeddings", help="Structure only; no vectors. Fast for Phase 1."
    ),
) -> None:
    code = asyncio.run(_run(only, reload_slug, skip_embeddings))
    raise typer.Exit(code)


if __name__ == "__main__":
    app()
