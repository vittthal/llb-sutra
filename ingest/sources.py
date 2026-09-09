"""Loading and validating the source manifest.

Two files, merged:

  ingest/sources.yaml        curated, committed. Public acts and treaties.
  ingest/sources.local.yaml  yours, gitignored. Anything you add locally —
                             textbooks, notes, question papers, syllabus.

Keeping them separate means you can `git pull` improvements to the curated manifest
without your own material ever being at risk of being committed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "ingest" / "sources.yaml"
LOCAL_MANIFEST = REPO_ROOT / "ingest" / "sources.local.yaml"
DATA_DIR = REPO_ROOT / "data"
INCOMING_DIR = DATA_DIR / "incoming"
MANUAL_DIR = DATA_DIR / "manual"

DOC_TYPES = {"bare_act", "judgment", "treaty", "syllabus", "pyq", "notes", "textbook"}
LICENCES = {"public", "govt-public", "owned-licensed", "excerpt-only"}


class ManifestError(ValueError):
    pass


@dataclass
class Subject:
    code: str
    name: str
    slug: str
    semester: int


@dataclass
class SourceDoc:
    title: str
    slug: str
    doc_type: str
    licence: str
    subject: str | None = None
    note: str | None = None
    act: dict[str, Any] | None = None
    fetch: list[str] = field(default_factory=list)
    indiacode_query: str | None = None
    local_path: str | None = None
    origin: str = "curated"  # curated | local

    def validate(self) -> None:
        if self.doc_type not in DOC_TYPES:
            raise ManifestError(
                f"{self.slug}: doc_type {self.doc_type!r} not in {sorted(DOC_TYPES)}"
            )
        if self.licence not in LICENCES:
            raise ManifestError(
                f"{self.slug}: licence {self.licence!r} not in {sorted(LICENCES)}"
            )
        if not self.fetch and not self.local_path and not self.indiacode_query:
            raise ManifestError(
                f"{self.slug}: needs one of fetch:, local_path: or indiacode_query:"
            )

    def resolved_path(self) -> Path:
        """Where the file lives (or will live) on disk."""
        if self.local_path:
            p = Path(self.local_path)
            return p if p.is_absolute() else REPO_ROOT / p
        return DATA_DIR / "fetched" / f"{self.slug}.pdf"


@dataclass
class Manifest:
    subjects: list[Subject]
    documents: list[SourceDoc]

    def subject_by_code(self, code: str) -> Subject | None:
        return next((s for s in self.subjects if s.code == code), None)

    def document_by_slug(self, slug: str) -> SourceDoc | None:
        return next((d for d in self.documents if d.slug == slug), None)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _to_docs(raw: list[dict[str, Any]] | None, origin: str) -> list[SourceDoc]:
    docs: list[SourceDoc] = []
    for entry in raw or []:
        docs.append(
            SourceDoc(
                title=entry["title"],
                slug=entry["slug"],
                doc_type=entry["doc_type"],
                licence=entry["licence"],
                subject=entry.get("subject"),
                note=entry.get("note"),
                act=entry.get("act"),
                fetch=entry.get("fetch") or [],
                indiacode_query=entry.get("indiacode_query"),
                local_path=entry.get("local_path"),
                origin=origin,
            )
        )
    return docs


def load_manifest() -> Manifest:
    curated = _read_yaml(MANIFEST)
    local = _read_yaml(LOCAL_MANIFEST)

    subjects = [
        Subject(code=s["code"], name=s["name"], slug=s["slug"], semester=s["semester"])
        for s in (curated.get("subjects") or [])
    ]
    # A local manifest may add subjects (another semester, say) but not silently
    # redefine a curated one.
    known = {s.code for s in subjects}
    for s in local.get("subjects") or []:
        if s["code"] not in known:
            subjects.append(
                Subject(code=s["code"], name=s["name"], slug=s["slug"], semester=s["semester"])
            )

    documents = _to_docs(curated.get("documents"), "curated")
    documents += _to_docs(curated.get("manual"), "curated")
    documents += _to_docs(local.get("documents"), "local")

    seen: set[str] = set()
    for doc in documents:
        doc.validate()
        if doc.slug in seen:
            raise ManifestError(f"duplicate slug: {doc.slug}")
        seen.add(doc.slug)
        if doc.subject and doc.subject not in {s.code for s in subjects}:
            raise ManifestError(
                f"{doc.slug}: unknown subject {doc.subject!r}; "
                f"known: {sorted({s.code for s in subjects})}"
            )

    return Manifest(subjects=subjects, documents=documents)


def append_local_document(entry: dict[str, Any]) -> None:
    """Append one document entry to sources.local.yaml, creating it if needed."""
    data = _read_yaml(LOCAL_MANIFEST)
    data.setdefault("documents", [])
    if any(d.get("slug") == entry["slug"] for d in data["documents"]):
        raise ManifestError(f"slug already in sources.local.yaml: {entry['slug']}")
    data["documents"].append(entry)
    header = (
        "# Your local sources. GITIGNORED — never committed.\n"
        "# Managed by `python -m ingest.add`; safe to hand-edit.\n"
    )
    with LOCAL_MANIFEST.open("w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=100)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
