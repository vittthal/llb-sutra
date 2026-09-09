"""Populate the `pyq` table from already-ingested question-paper documents.

Runs after `ingest.load` (which stores the papers as documents + chunks). Kept
separate so the parser can be re-run and improved without re-OCRing the scans, which
is by far the slowest step.

    python -m ingest.load_pyqs            # parse every pyq document
    python -m ingest.load_pyqs --dry-run  # show what would be inserted
    python -m ingest.load_pyqs --reset    # clear the table and re-parse
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from backend.app.db import close_pool, transaction
from ingest.parse_pyq import parse_exam_label, parse_paper

app = typer.Typer(add_completion=False)
console = Console()


async def _run(dry_run: bool, reset: bool) -> int:
    rows_out: list[tuple[str, int, str]] = []

    async with transaction() as conn:
        if reset and not dry_run:
            await conn.execute("DELETE FROM pyq")
            console.print("[yellow]cleared pyq table[/yellow]")

        docs = await conn.fetch(
            """
            SELECT d.id, d.title, d.subject_id
            FROM document d
            WHERE d.doc_type = 'pyq'
            ORDER BY d.id
            """
        )

        for doc in docs:
            text = await conn.fetchval(
                """
                SELECT string_agg(text, ' ' ORDER BY ord)
                FROM chunk WHERE document_id = $1
                """,
                doc["id"],
            )
            if not text:
                rows_out.append((doc["title"], 0, "no text"))
                continue

            year, exam = parse_exam_label(doc["title"])
            questions = parse_paper(text)

            if not questions:
                rows_out.append((doc["title"], 0, "parsed nothing"))
                continue
            if year is None:
                rows_out.append((doc["title"], 0, "no year in title"))
                continue
            if doc["subject_id"] is None:
                rows_out.append((doc["title"], 0, "no subject"))
                continue

            if not dry_run:
                await conn.executemany(
                    """
                    INSERT INTO pyq
                        (subject_id, year, exam, marks, question_no, question_text)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    [
                        (doc["subject_id"], year, exam, q.marks, q.question_no, q.question_text)
                        for q in questions
                    ],
                )

            with_marks = sum(1 for q in questions if q.marks is not None)
            rows_out.append(
                (doc["title"], len(questions), f"{exam}, {with_marks} with marks")
            )

    table = Table(title="dry run" if dry_run else "pyq load")
    table.add_column("paper", style="cyan", overflow="fold")
    table.add_column("questions", justify="right")
    table.add_column("detail", overflow="fold")
    for title, n, detail in rows_out:
        table.add_row(title[:44], str(n), detail)
    console.print(table)
    console.print(f"[green]total questions: {sum(n for _, n, _ in rows_out)}[/green]")

    await close_pool()
    return 0


@app.command()
def main(
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse but do not insert."),
    reset: bool = typer.Option(False, "--reset", help="Clear pyq table first."),
) -> None:
    raise typer.Exit(asyncio.run(_run(dry_run, reset)))


if __name__ == "__main__":
    app()
