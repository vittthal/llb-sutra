"""Download PDFs from a PUBLIC Google Drive folder.

Question papers live in shared Drive folders, and Drive's normal folder page is
JavaScript-rendered, so it cannot be scraped. The `embeddedfolderview` endpoint still
returns plain HTML listing for publicly-shared folders, which is what this uses.

    python -m ingest.fetch_drive <folder_id> --dest data/incoming/CPC/pyq --match 75-25
    python -m ingest.fetch_drive <folder_id> --list-only

`--match` matters here: Mumbai University ran a 60-40 pattern and now runs 75-25, and
mixing the two would corrupt the PYQ analytics — question counts, mark weights and
paper structure all differ. Filter to one pattern per ingest.

Downloaded files land in a drop folder, so the normal flow continues with:

    python -m ingest.add scan
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from backend.app.config import settings

app = typer.Typer(add_completion=False)
console = Console()

FOLDER_VIEW = "https://drive.google.com/embeddedfolderview?id={folder_id}#list"
DOWNLOAD = "https://drive.google.com/uc?export=download&id={file_id}"

# <div class="flip-entry" id="entry-<ID>"> ... <div class="flip-entry-title">NAME</div>
ENTRY_RE = re.compile(
    r'id="entry-(?P<id>[\w-]+)".*?flip-entry-title">(?P<name>[^<]+)<',
    re.DOTALL,
)


def _client() -> httpx.Client:
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass
    return httpx.Client(
        headers={"User-Agent": settings.fetch_user_agent},
        follow_redirects=True,
        timeout=httpx.Timeout(120.0, connect=20.0),
    )


def list_folder(client: httpx.Client, folder_id: str) -> list[tuple[str, str]]:
    """Return [(file_id, name)] for a public folder."""
    resp = client.get(FOLDER_VIEW.format(folder_id=folder_id))
    resp.raise_for_status()
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for m in ENTRY_RE.finditer(resp.text):
        fid, name = m.group("id"), m.group("name").strip()
        if fid not in seen:
            seen.add(fid)
            out.append((fid, name))
    return out


def download(client: httpx.Client, file_id: str, dest: Path) -> tuple[bool, str]:
    resp = client.get(DOWNLOAD.format(file_id=file_id))
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"
    content = resp.content
    if content[:4] != b"%PDF":
        # Drive serves an HTML interstitial for large files or non-public items.
        return False, f"not a PDF ({len(content)}b) - check the folder is public"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return True, f"{len(content)}b"


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w\s.-]", "", name).strip().replace(" ", "-")
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


@app.command()
def main(
    folder_id: str = typer.Argument(..., help="Public Google Drive folder ID."),
    dest: Path = typer.Option(None, "--dest", help="Destination directory."),
    match: str = typer.Option(None, "--match", help="Only files whose name contains this."),
    list_only: bool = typer.Option(False, "--list-only", help="List, download nothing."),
) -> None:
    with _client() as client:
        entries = list_folder(client, folder_id)
        if match:
            entries = [(i, n) for i, n in entries if match.lower() in n.lower()]

        if not entries:
            console.print("[yellow]no matching files[/yellow]")
            raise typer.Exit(1)

        table = Table(title=f"{len(entries)} file(s)")
        table.add_column("name", style="cyan", overflow="fold")
        table.add_column("result")
        for fid, name in entries:
            if list_only:
                table.add_row(name, "[dim]listed[/dim]")
                continue
            target = (dest or Path("data/incoming")) / _safe_name(name)
            if target.exists():
                table.add_row(name, "[dim]cached[/dim]")
                continue
            ok, detail = download(client, fid, target)
            table.add_row(name, f"[green]{detail}[/green]" if ok else f"[red]{detail}[/red]")
        console.print(table)


if __name__ == "__main__":
    app()
