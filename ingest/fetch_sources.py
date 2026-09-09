"""Fetch public source documents.

Design note, learned the hard way: India Code direct `bitstream` URLs are NOT stable.
Every hardcoded bitstream ID tested during planning returned 404, and the site itself is
a JavaScript SPA whose HTML pages are ~2KB shells, so scraping them yields nothing.

What does work is the India Code DSpace REST API. So the strategy is:

  1. try each URL in the manifest `fetch:` list, in order (known-good mirrors first)
  2. if all fail, resolve through the India Code search API using `indiacode_query`,
     or a query derived from act.short_title + act.year
  3. report what could not be resolved, loudly, rather than leaving a silent gap

Government portals reject default HTTP clients, so every request carries a real
User-Agent and the crawl is rate-limited.

    python -m ingest.fetch_sources --dry-run     # check reachability, download nothing
    python -m ingest.fetch_sources               # fetch everything missing
    python -m ingest.fetch_sources --only bnss-2023
    python -m ingest.fetch_sources --force       # re-download even if cached
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx
import typer
from rich.console import Console
from rich.table import Table

from backend.app.config import settings
from ingest.sources import DATA_DIR, SourceDoc, load_manifest, sha256_file

app = typer.Typer(add_completion=False)
console = Console()

FETCH_DIR = DATA_DIR / "fetched"
INDIACODE_SEARCH = "https://indiacode.gov.in/server/api/discover/search/objects"
INDIACODE_BASE = "https://indiacode.gov.in"

PDF_MAGIC = b"%PDF"


@dataclass
class FetchResult:
    slug: str
    ok: bool
    detail: str
    url: str | None = None
    size: int = 0


def _use_os_trust_store() -> None:
    """Verify TLS against the operating system trust store, not certifi.

    Several Indian government portals (egazette.gov.in among them) serve certificates
    from CAs that are in the Windows/macOS trust store but NOT in certifi's bundle.
    Without this, httpx raises CERTIFICATE_VERIFY_FAILED on sources a browser opens
    without complaint.

    The alternative — verify=False — would silently accept any certificate, including
    an intercepted one. Not acceptable for a tool whose entire value is provenance.
    """
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:  # pragma: no cover - optional, degrades to certifi
        console.print("[dim]truststore not installed; some govt portals may fail TLS[/dim]")


def _client() -> httpx.Client:
    _use_os_trust_store()
    return httpx.Client(
        headers={
            "User-Agent": settings.fetch_user_agent,
            "Accept": "application/pdf,application/json,*/*",
        },
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, connect=20.0),
    )


def _looks_like_pdf(content: bytes) -> bool:
    """Trust magic bytes over Content-Type.

    India Code serves HTML error pages with a 200 status, so a header check alone
    would happily save a 2KB error page as a bare act.
    """
    return content[:4] == PDF_MAGIC


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for title phrase matching."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _verify_is_expected_act(content: bytes, doc: SourceDoc) -> tuple[bool, str]:
    """Check a downloaded PDF really is the act we asked for.

    This exists because the India Code search API is fuzzy and cheerfully returns
    plausible-but-wrong documents. Observed in practice: a request for the Limitation
    Act 1963 returned the *Andhra Pradesh State Co-operative Bank (Formation) Act 1963*;
    a request for the Factories Act 1948 returned the *East Punjab Factories (Control of
    Dismantling) Act*; a request for the Trade Unions Act returned a 1982 Punjab
    notification made under it.

    Every one of those is a valid PDF, so a magic-bytes check passes them. Loading them
    would silently poison the corpus with the wrong statute — the worst failure mode
    this project has. Two guards:

      1. the act's short title must appear as a PHRASE in the opening pages
         ("factories act" is absent from "factories control of dismantling act")
      2. a bare act must yield a plausible number of sections, which rejects
         notifications and single-page extracts that happen to quote the title
    """
    try:
        import pymupdf

        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            head = "\n".join(page.get_text("text") or "" for page in pdf[:5])
            n_pages = pdf.page_count
    except Exception as exc:  # unreadable PDF is itself a rejection
        return False, f"unreadable PDF ({type(exc).__name__})"

    expected = (doc.act or {}).get("short_title") or doc.title
    # Drop a leading "The" and any trailing year for phrase matching.
    phrase = _normalise(re.sub(r"^the\s+", "", expected, flags=re.I))
    haystack = _normalise(head)

    if phrase and phrase not in haystack:
        return False, f"title {phrase!r} not found in first pages"

    if doc.doc_type == "bare_act" and n_pages < 8:
        return False, f"only {n_pages} pages - looks like a notification or extract"

    return True, "verified"


def _indiacode_query_for(doc: SourceDoc) -> str | None:
    if doc.indiacode_query:
        return doc.indiacode_query
    if doc.act:
        title = doc.act.get("short_title")
        year = doc.act.get("year")
        if title:
            return f"{title} {year}" if year else str(title)
    return None


def _resolve_via_indiacode(client: httpx.Client, query: str) -> list[str]:
    """Search India Code and return candidate bitstream download URLs."""
    try:
        resp = client.get(INDIACODE_SEARCH, params={"query": query, "size": 10})
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        console.print(f"[dim]  indiacode search failed: {exc}[/dim]")
        return []

    objects = (
        payload.get("_embedded", {})
        .get("searchResult", {})
        .get("_embedded", {})
        .get("objects", [])
    )

    urls: list[str] = []
    for obj in objects:
        item = obj.get("_embedded", {}).get("indexableObject", {})
        uuid = item.get("uuid")
        if not uuid:
            continue
        # DSpace 7 shape: item -> bundles -> bitstreams -> content
        try:
            bundles = client.get(f"{INDIACODE_BASE}/server/api/core/items/{uuid}/bundles")
            bundles.raise_for_status()
            for bundle in bundles.json().get("_embedded", {}).get("bundles", []):
                bs_href = bundle.get("_links", {}).get("bitstreams", {}).get("href")
                if not bs_href:
                    continue
                bits = client.get(bs_href)
                bits.raise_for_status()
                for bit in bits.json().get("_embedded", {}).get("bitstreams", []):
                    href = bit.get("_links", {}).get("content", {}).get("href")
                    name = (bit.get("name") or "").lower()
                    if href and (name.endswith(".pdf") or not name):
                        urls.append(href)
        except (httpx.HTTPError, ValueError):
            continue
        time.sleep(settings.fetch_rate_limit_seconds)
    return urls


def _try_urls(
    client: httpx.Client, urls: list[str], doc: SourceDoc, *, dry_run: bool
) -> tuple[bytes | None, str | None, str]:
    """Return (content, winning_url, detail). content is None in dry-run."""
    last = "no candidate URLs"
    for url in urls:
        try:
            resp = client.get(url)
            resp.raise_for_status()
            content = resp.content
            if not _looks_like_pdf(content):
                ctype = resp.headers.get("content-type")
                last = f"not a PDF (content-type={ctype}, {len(content)}b)"
                console.print(f"[dim]  reject {url} -> {last}[/dim]")
                time.sleep(settings.fetch_rate_limit_seconds)
                continue
            ok, why = _verify_is_expected_act(content, doc)
            if not ok:
                last = f"wrong document: {why}"
                console.print(f"[yellow]  reject {url} -> {last}[/yellow]")
                time.sleep(settings.fetch_rate_limit_seconds)
                continue
            return (None if dry_run else content), url, f"{len(content)}b"
        except httpx.HTTPStatusError as exc:
            last = f"HTTP {exc.response.status_code}"
        except httpx.HTTPError as exc:
            last = type(exc).__name__
        console.print(f"[dim]  miss {url} -> {last}[/dim]")
        time.sleep(settings.fetch_rate_limit_seconds)
    return None, None, last


def fetch_one(client: httpx.Client, doc: SourceDoc, *, dry_run: bool, force: bool) -> FetchResult:
    if doc.local_path:
        path = doc.resolved_path()
        if path.exists():
            return FetchResult(doc.slug, True, f"local {path.name}", size=path.stat().st_size)
        return FetchResult(doc.slug, False, f"local file missing: {path}")

    dest = FETCH_DIR / f"{doc.slug}.pdf"
    if dest.exists() and not force:
        return FetchResult(doc.slug, True, "cached", size=dest.stat().st_size)

    console.print(f"[bold]{doc.slug}[/bold]")
    content, url, detail = _try_urls(client, doc.fetch, doc, dry_run=dry_run)

    if url is None:
        query = _indiacode_query_for(doc)
        if query:
            console.print(f"[dim]  falling back to India Code search: {query!r}[/dim]")
            candidates = _resolve_via_indiacode(client, query)
            if candidates:
                content, url, detail = _try_urls(client, candidates, doc, dry_run=dry_run)

    if url is None:
        return FetchResult(doc.slug, False, detail)

    if dry_run:
        return FetchResult(doc.slug, True, f"reachable ({detail})", url=url)

    FETCH_DIR.mkdir(parents=True, exist_ok=True)
    assert content is not None
    dest.write_bytes(content)
    return FetchResult(doc.slug, True, sha256_file(dest)[:12], url=url, size=len(content))


@app.command()
def main(
    dry_run: bool = typer.Option(False, "--dry-run", help="Check reachability, download nothing."),
    force: bool = typer.Option(False, "--force", help="Re-download even if cached."),
    only: str = typer.Option(None, "--only", help="Fetch a single slug."),
) -> None:
    manifest = load_manifest()
    docs = [d for d in manifest.documents if not only or d.slug == only]
    if not docs:
        console.print(f"[red]no document matching {only!r}[/red]")
        raise typer.Exit(1)

    results: list[FetchResult] = []
    with _client() as client:
        for doc in docs:
            results.append(fetch_one(client, doc, dry_run=dry_run, force=force))

    table = Table(title="dry run" if dry_run else "fetch")
    table.add_column("slug", style="cyan")
    table.add_column("ok")
    table.add_column("detail", overflow="fold")
    for r in results:
        table.add_row(r.slug, "[green]yes[/green]" if r.ok else "[red]NO[/red]", r.detail)
    console.print(table)

    failed = [r for r in results if not r.ok]
    if failed:
        console.print(
            f"[yellow]{len(failed)} unresolved:[/yellow] {', '.join(r.slug for r in failed)}"
        )
        console.print(
            "[dim]For these, download the PDF by hand into data/manual/ and register it:\n"
            '  python -m ingest.add file data/manual/<file>.pdf --title "..." '
            "--type bare_act --licence govt-public --subject CPC[/dim]"
        )
        raise typer.Exit(1)
    console.print(f"[green]{len(results)} source(s) OK[/green]")


if __name__ == "__main__":
    app()
