"""Populate `module` and `topic` from the ingested syllabus documents.

    python -m ingest.load_syllabus --dry-run
    python -m ingest.load_syllabus --reset
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table
from slugify import slugify

from backend.app.db import close_pool, transaction
from ingest.parse_syllabus import parse_subject

app = typer.Typer(add_completion=False)
console = Console()

SUBJECTS = ["CPC", "BNSS", "LABOUR2", "PIL"]


async def _run(dry_run: bool, reset: bool) -> int:
    rows: list[tuple[str, int, int, str]] = []

    async with transaction() as conn:
        if reset and not dry_run:
            # topic cascades from module
            await conn.execute("DELETE FROM module")
            console.print("[yellow]cleared module/topic[/yellow]")

        text = await conn.fetchval(
            """
            SELECT string_agg(c.text, ' ' ORDER BY d.id, c.ord)
            FROM chunk c JOIN document d ON d.id = c.document_id
            WHERE d.doc_type = 'syllabus'
            """
        )
        if not text:
            console.print("[red]no syllabus documents ingested[/red]")
            await close_pool()
            return 1

        for code in SUBJECTS:
            subject_id = await conn.fetchval("SELECT id FROM subject WHERE code = $1", code)
            if subject_id is None:
                rows.append((code, 0, 0, "subject not found"))
                continue

            modules = parse_subject(text, code)
            if not modules:
                rows.append((code, 0, 0, "no course block matched"))
                continue

            n_topics = 0
            for mod in modules:
                title = mod.title
                if mod.section_from and mod.section_to:
                    title = f"{title} (ss. {mod.section_from}–{mod.section_to})"

                if dry_run:
                    n_topics += len(mod.topics)
                    continue

                module_id = await conn.fetchval(
                    """
                    INSERT INTO module (subject_id, number, title)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (subject_id, number)
                    DO UPDATE SET title = EXCLUDED.title
                    RETURNING id
                    """,
                    subject_id,
                    mod.number,
                    title[:300],
                )
                for topic in mod.topics:
                    slug = slugify(f"{code}-{mod.number}-{topic.number or ''}-{topic.title}")[:90]
                    await conn.execute(
                        """
                        INSERT INTO topic (module_id, title, slug, keywords)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title
                        """,
                        module_id,
                        topic.title[:300],
                        slug,
                        [w for w in topic.title.lower().split() if len(w) > 4][:8],
                    )
                    n_topics += 1

            preview = modules[0].title[:44]
            rows.append((code, len(modules), n_topics, preview))

    table = Table(title="dry run" if dry_run else "syllabus load")
    table.add_column("subject", style="cyan")
    table.add_column("modules", justify="right")
    table.add_column("topics", justify="right")
    table.add_column("first module", overflow="fold")
    for code, m, t, note in rows:
        table.add_row(code, str(m), str(t), note)
    console.print(table)

    await close_pool()
    return 0


@app.command()
def main(
    dry_run: bool = typer.Option(False, "--dry-run"),
    reset: bool = typer.Option(False, "--reset"),
) -> None:
    raise typer.Exit(asyncio.run(_run(dry_run, reset)))


if __name__ == "__main__":
    app()
