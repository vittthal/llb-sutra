"""Add your own PDFs as sources, without hand-editing YAML.

Two ways in.

1. Drop-folder — put PDFs under data/incoming/ and run:

       python -m ingest.add scan

   Folder layout drives the metadata, so you can bulk-drop a semester at once:

       data/incoming/<SUBJECT>/<doc_type>/<file>.pdf
       data/incoming/CPC/notes/res-judicata.pdf      -> subject CPC, doc_type notes
       data/incoming/CPC/pyq/nov-2024.pdf            -> subject CPC, doc_type pyq
       data/incoming/syllabus/sem5.pdf               -> doc_type syllabus, no subject

   Anything it cannot infer, it asks about — or you override with flags.

2. One file, explicitly:

       python -m ingest.add file data/manual/takwani.pdf \\
           --title "Takwani, Civil Procedure" --type textbook \\
           --subject CPC --licence owned-licensed

LICENCE DEFAULT IS DELIBERATELY RESTRICTIVE. Anything added this way defaults to
`owned-licensed` (retrieval only, 200-char excerpt ceiling) unless you say otherwise.
The failure mode of guessing wrong should be serving too little, never republishing
someone's textbook. Widen it consciously, per file.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from slugify import slugify

from ingest.sources import (
    DOC_TYPES,
    INCOMING_DIR,
    LICENCES,
    MANUAL_DIR,
    REPO_ROOT,
    ManifestError,
    append_local_document,
    load_manifest,
)

app = typer.Typer(add_completion=False, help="Add local PDFs to the source manifest.")
console = Console()

# Folder name -> doc_type. Generous aliases, because you will not remember the enum.
_TYPE_ALIASES = {
    "notes": "notes",
    "note": "notes",
    "pyq": "pyq",
    "pyqs": "pyq",
    "papers": "pyq",
    "questionpapers": "pyq",
    "syllabus": "syllabus",
    "act": "bare_act",
    "acts": "bare_act",
    "bareact": "bare_act",
    "bare_act": "bare_act",
    "judgment": "judgment",
    "judgments": "judgment",
    "cases": "judgment",
    "caselaw": "judgment",
    "treaty": "treaty",
    "treaties": "treaty",
    "book": "textbook",
    "books": "textbook",
    "textbook": "textbook",
}

# doc_type -> the licence that is correct for it far more often than not.
_LICENCE_BY_TYPE = {
    "bare_act": "govt-public",
    "judgment": "govt-public",
    "treaty": "public",
    "syllabus": "govt-public",
    "pyq": "govt-public",
    "notes": "owned-licensed",
    "textbook": "owned-licensed",
}


def _infer_from_path(pdf: Path, root: Path) -> tuple[str | None, str | None]:
    """Infer (subject_code, doc_type) from the folder path under the drop root."""
    try:
        parts = pdf.relative_to(root).parts[:-1]
    except ValueError:
        return None, None

    subject: str | None = None
    doc_type: str | None = None
    known_subjects = {s.code.lower(): s.code for s in load_manifest().subjects}

    for part in parts:
        key = part.lower().replace("-", "").replace("_", "").replace(" ", "")
        if key in _TYPE_ALIASES and doc_type is None:
            doc_type = _TYPE_ALIASES[key]
        elif part.lower() in known_subjects and subject is None:
            subject = known_subjects[part.lower()]
    return subject, doc_type


def _register(
    *,
    pdf: Path,
    title: str,
    doc_type: str,
    licence: str,
    subject: str | None,
    copy_into_manual: bool,
) -> dict:
    if doc_type not in DOC_TYPES:
        raise typer.BadParameter(f"--type must be one of {sorted(DOC_TYPES)}")
    if licence not in LICENCES:
        raise typer.BadParameter(f"--licence must be one of {sorted(LICENCES)}")

    dest = pdf
    if copy_into_manual:
        MANUAL_DIR.mkdir(parents=True, exist_ok=True)
        dest = MANUAL_DIR / pdf.name
        if dest.resolve() != pdf.resolve():
            shutil.copy2(pdf, dest)

    rel = dest.relative_to(REPO_ROOT) if dest.is_relative_to(REPO_ROOT) else dest
    entry = {
        "title": title,
        "slug": slugify(title)[:80],
        "doc_type": doc_type,
        "licence": licence,
        "local_path": str(rel).replace("\\", "/"),
    }
    if subject:
        entry["subject"] = subject
    append_local_document(entry)
    return entry


@app.command("file")
def add_file(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    title: str = typer.Option(None, "--title", "-t", help="Defaults to the filename."),
    doc_type: str = typer.Option(None, "--type", help=f"One of {sorted(DOC_TYPES)}"),
    licence: str = typer.Option(None, "--licence", help=f"One of {sorted(LICENCES)}"),
    subject: str = typer.Option(None, "--subject", "-s", help="Subject code, e.g. CPC"),
    copy: bool = typer.Option(True, "--copy/--in-place", help="Copy into data/manual/"),
) -> None:
    """Register a single PDF as a source."""
    title = title or path.stem.replace("-", " ").replace("_", " ").title()
    doc_type = doc_type or typer.prompt(f"doc_type {sorted(DOC_TYPES)}", default="notes")
    licence = licence or _LICENCE_BY_TYPE.get(doc_type, "owned-licensed")

    try:
        entry = _register(
            pdf=path,
            title=title,
            doc_type=doc_type,
            licence=licence,
            subject=subject,
            copy_into_manual=copy,
        )
    except ManifestError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"[green]added[/green] {entry['slug']}  ({entry['doc_type']}, {entry['licence']})")
    console.print("Next: [bold]python -m ingest.load[/bold]")


@app.command("scan")
def scan(
    root: Path = typer.Option(INCOMING_DIR, "--root", help="Drop folder to scan."),
    licence: str = typer.Option(None, "--licence", help="Force one licence for everything."),
    subject: str = typer.Option(None, "--subject", "-s", help="Force one subject code."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Register without confirming."),
) -> None:
    """Scan a drop folder and register every PDF it finds."""
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
        console.print(f"Created [bold]{root}[/bold] — drop PDFs in there and run this again.")
        console.print("Layout: data/incoming/<SUBJECT>/<notes|pyq|acts|cases>/file.pdf")
        raise typer.Exit(0)

    pdfs = sorted(p for p in root.rglob("*.pdf") if p.is_file())
    if not pdfs:
        console.print(f"No PDFs under [bold]{root}[/bold].")
        raise typer.Exit(0)

    manifest = load_manifest()
    known_paths = {d.local_path for d in manifest.documents if d.local_path}

    planned: list[dict] = []
    for pdf in pdfs:
        inferred_subject, inferred_type = _infer_from_path(pdf, root)
        doc_type = inferred_type or "notes"
        planned.append(
            {
                "path": pdf,
                "title": pdf.stem.replace("-", " ").replace("_", " ").title(),
                "doc_type": doc_type,
                "licence": licence or _LICENCE_BY_TYPE.get(doc_type, "owned-licensed"),
                "subject": subject or inferred_subject,
            }
        )

    table = Table(title=f"{len(planned)} PDF(s) under {root}")
    table.add_column("file", style="cyan", overflow="fold")
    table.add_column("type")
    table.add_column("subject")
    table.add_column("licence", style="yellow")
    for p in planned:
        table.add_row(
            str(p["path"].relative_to(root)),
            p["doc_type"],
            p["subject"] or "-",
            p["licence"],
        )
    console.print(table)
    console.print(
        "[dim]owned-licensed = retrieval only, 200-char excerpt ceiling. "
        "Override per file with `ingest.add file`.[/dim]"
    )

    if not yes and not typer.confirm("Register these?", default=True):
        raise typer.Exit(0)

    added = 0
    for p in planned:
        rel = str(p["path"].relative_to(REPO_ROOT)).replace("\\", "/")
        if rel in known_paths:
            console.print(f"[dim]skip (already registered) {rel}[/dim]")
            continue
        try:
            _register(
                pdf=p["path"],
                title=p["title"],
                doc_type=p["doc_type"],
                licence=p["licence"],
                subject=p["subject"],
                copy_into_manual=False,
            )
            added += 1
        except ManifestError as exc:
            console.print(f"[yellow]skip[/yellow] {rel}: {exc}")

    console.print(f"[green]registered {added} document(s)[/green]")
    console.print("Next: [bold]python -m ingest.load[/bold]")


@app.command("list")
def list_sources() -> None:
    """Show every registered source and where it came from."""
    manifest = load_manifest()
    table = Table(title="Sources")
    table.add_column("slug", style="cyan")
    table.add_column("type")
    table.add_column("subject")
    table.add_column("licence", style="yellow")
    table.add_column("origin", style="dim")
    for d in manifest.documents:
        table.add_row(d.slug, d.doc_type, d.subject or "-", d.licence, d.origin)
    console.print(table)


if __name__ == "__main__":
    try:
        app()
    except ManifestError as exc:
        console.print(f"[red]manifest error:[/red] {exc}")
        sys.exit(1)
