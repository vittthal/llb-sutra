"""Copy the local corpus into a hosted Postgres (Neon, Supabase, anything).

The corpus is built locally — fetching, OCR and embedding are all far too heavy for a
free instance — and then pushed. This script applies the schema and copies every table
in dependency order.

    # 1. create a free Neon project, copy its connection string
    # 2. push
    python -m deploy.push_to_neon "postgresql://user:pass@host/db?sslmode=require"

    # check first, change nothing
    python -m deploy.push_to_neon "<url>" --dry-run

Re-runnable: --reset drops and recreates the schema, so a corpus rebuild is one command.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg
import typer
from rich.console import Console
from rich.table import Table

from backend.app.config import settings

app = typer.Typer(add_completion=False)
console = Console()

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "migrations" / "001_init.sql"

# Parent tables first: every table here depends only on those above it.
TABLES = [
    "subject", "module", "topic",
    "act", "provision", "provision_map",
    "case_law", "case_topic",
    "pyq",
    "document", "chunk",
]

# Sequences to realign after copying explicit ids.
SEQUENCES = {
    "subject": "id", "module": "id", "topic": "id", "act": "id",
    "provision": "id", "case_law": "id", "pyq": "id",
    "document": "id", "chunk": "id",
}

BATCH = 500


async def _copy_table(src: asyncpg.Connection, dst: asyncpg.Connection, table: str) -> int:
    columns = [
        r["column_name"]
        for r in await src.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name=$1
            ORDER BY ordinal_position
            """,
            table,
        )
    ]
    if not columns:
        return 0

    # embedding is a pgvector type; asyncpg has no codec for it, so it moves as text
    # and is cast back on insert.
    select_cols = ", ".join(
        f"{c}::text" if c == "embedding" else c for c in columns
    )
    rows = await src.fetch(f"SELECT {select_cols} FROM {table}")
    if not rows:
        return 0

    placeholders = ", ".join(
        f"${i}::vector" if c == "embedding" else f"${i}"
        for i, c in enumerate(columns, start=1)
    )
    stmt = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    )

    total = 0
    for start in range(0, len(rows), BATCH):
        batch = rows[start : start + BATCH]
        await dst.executemany(stmt, [tuple(r) for r in batch])
        total += len(batch)
    return total


async def _run(target_url: str, dry_run: bool, reset: bool) -> int:
    if SCHEMA.exists() is False:
        console.print(f"[red]schema not found: {SCHEMA}[/red]")
        return 1

    src = await asyncpg.connect(settings.dsn)
    console.print(f"[dim]source: {settings.postgres_host}/{settings.postgres_db}[/dim]")

    counts = {t: await src.fetchval(f"SELECT count(*) FROM {t}") for t in TABLES}
    table = Table(title="local corpus")
    table.add_column("table", style="cyan")
    table.add_column("rows", justify="right")
    for t, n in counts.items():
        table.add_row(t, str(n))
    console.print(table)

    if dry_run:
        console.print("[yellow]dry run — target untouched[/yellow]")
        await src.close()
        return 0

    dst = await asyncpg.connect(target_url)
    try:
        if reset:
            console.print("[yellow]dropping public schema on target[/yellow]")
            await dst.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

        existing = await dst.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
        )
        if not existing:
            console.print("applying schema…")
            await dst.execute(SCHEMA.read_text(encoding="utf-8"))

        results = []
        for t in TABLES:
            n = await _copy_table(src, dst, t)
            results.append((t, n))
            console.print(f"  {t}: {n}")

        for t, col in SEQUENCES.items():
            await dst.execute(
                f"SELECT setval(pg_get_serial_sequence('{t}', '{col}'), "
                f"coalesce((SELECT max({col}) FROM {t}), 1), true)"
            )

        total = sum(n for _, n in results)
        console.print(f"[green]copied {total} rows[/green]")
        embedded = await dst.fetchval("SELECT count(embedding) FROM chunk")
        console.print(f"[green]chunks with embeddings on target: {embedded}[/green]")
    finally:
        await dst.close()
        await src.close()
    return 0


@app.command()
def main(
    target_url: str = typer.Argument(..., help="Target Postgres connection string."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; change nothing."),
    reset: bool = typer.Option(False, "--reset", help="Drop the target schema first."),
) -> None:
    raise typer.Exit(asyncio.run(_run(target_url, dry_run, reset)))


if __name__ == "__main__":
    app()
