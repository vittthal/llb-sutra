"""Backfill embeddings for chunks that do not have one yet.

Separate from `ingest.load` on purpose. `load` is keyed on a document checksum and
skips anything unchanged, which is right for ingestion but means it will never
revisit a document to add vectors. Embedding is also the slowest and most
interruptible step, so it needs to be resumable on its own:

    python -m ingest.embed_missing              # embed everything still NULL
    python -m ingest.embed_missing --limit 500  # a batch at a time
    python -m ingest.embed_missing --stats      # how much is left

Safe to re-run and safe to kill: it only ever touches rows where embedding IS NULL,
and commits per batch.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.progress import Progress

from backend.app.db import close_pool, connection
from ingest.embed import embed_documents, to_pgvector

app = typer.Typer(add_completion=False)
console = Console()

BATCH = 128


async def _stats() -> None:
    async with connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT count(*) AS total,
                   count(embedding) AS embedded,
                   count(*) - count(embedding) AS missing
            FROM chunk
            """
        )
    console.print(
        f"chunks: [bold]{row['total']}[/bold] total, "
        f"[green]{row['embedded']}[/green] embedded, "
        f"[yellow]{row['missing']}[/yellow] missing"
    )
    await close_pool()


async def _run(limit: int | None) -> None:
    async with connection() as conn:
        missing = await conn.fetchval("SELECT count(*) FROM chunk WHERE embedding IS NULL")
        if not missing:
            console.print("[green]nothing to embed[/green]")
            await close_pool()
            return

        target = min(missing, limit) if limit else missing
        console.print(f"embedding {target} of {missing} chunk(s)")

        done = 0
        with Progress() as progress:
            task = progress.add_task("embedding", total=target)
            while done < target:
                rows = await conn.fetch(
                    """
                    SELECT id, text FROM chunk
                    WHERE embedding IS NULL
                    ORDER BY id
                    LIMIT $1
                    """,
                    min(BATCH, target - done),
                )
                if not rows:
                    break

                vectors = embed_documents(r["text"] for r in rows)
                # executemany keeps this one round trip per batch rather than per row.
                await conn.executemany(
                    "UPDATE chunk SET embedding = $2::vector WHERE id = $1",
                    [(r["id"], to_pgvector(v)) for r, v in zip(rows, vectors, strict=True)],
                )
                done += len(rows)
                progress.update(task, advance=len(rows))

        console.print(f"[green]embedded {done} chunk(s)[/green]")
    await close_pool()


@app.command()
def main(
    limit: int = typer.Option(None, "--limit", help="Only embed this many chunks."),
    stats: bool = typer.Option(False, "--stats", help="Report progress and exit."),
) -> None:
    asyncio.run(_stats() if stats else _run(limit))


if __name__ == "__main__":
    app()
