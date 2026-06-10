"""Citation formatting — BibTeX, APA, and MLA from stored Source metadata.

Pure string formatting, no I/O. Works with whatever metadata we have; missing
fields degrade gracefully (e.g. a web source with no authors still produces a
valid web citation with an access note).
"""
from __future__ import annotations

import re
from datetime import date
from typing import List, Optional
from urllib.parse import urlparse

_FORMATS = ("bibtex", "apa", "mla")


def _authors_list(authors: Optional[str]) -> List[str]:
    if not authors:
        return []
    return [a.strip() for a in authors.split(";") if a.strip()]


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        host = ""
    return host[4:] if host.startswith("www.") else host


def _cite_key(source) -> str:
    first = _authors_list(source.authors)
    last = re.sub(r"[^A-Za-z]", "", first[0].split(",")[0]) if first else _domain(source.url).split(".")[0]
    return f"{last or 'source'}{source.year or ''}_{source.id}"


def _apa_authors(authors: List[str]) -> str:
    """APA-ish 'Last, F.' join. Authors are already stored 'Last, Initials'."""
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) <= 7:
        return ", ".join(authors[:-1]) + ", & " + authors[-1]
    return ", ".join(authors[:6]) + ", … " + authors[-1]


def format_bibtex(source) -> str:
    authors = _authors_list(source.authors)
    entry_type = {
        "journal": "article",
        "medical": "article",
        "preprint": "misc",
    }.get(source.source_type, "misc")
    fields = [f"  title = {{{source.title}}}"]
    if authors:
        fields.append("  author = {" + " and ".join(authors) + "}")
    if source.year:
        fields.append(f"  year = {{{source.year}}}")
    if source.venue:
        key = "journal" if entry_type == "article" else "howpublished"
        fields.append(f"  {key} = {{{source.venue}}}")
    if source.doi:
        fields.append(f"  doi = {{{source.doi}}}")
    fields.append(f"  url = {{{source.url}}}")
    return f"@{entry_type}{{{_cite_key(source)},\n" + ",\n".join(fields) + "\n}"


def format_apa(source) -> str:
    authors = _apa_authors(_authors_list(source.authors))
    year = f"({source.year})." if source.year else "(n.d.)."
    title = source.title.rstrip(".") + "."
    venue = f" *{source.venue}*." if source.venue else ""
    doi = f" https://doi.org/{source.doi}" if source.doi else f" {source.url}"
    lead = f"{authors} " if authors else ""
    return f"{lead}{year} {title}{venue}{doi}".strip()


def format_mla(source) -> str:
    authors = _authors_list(source.authors)
    lead = f"{authors[0]}" + (" et al. " if len(authors) > 1 else " ") if authors else ""
    title = f'"{source.title.rstrip(".")}." '
    venue = f"*{source.venue}*, " if source.venue else ""
    year = f"{source.year}, " if source.year else ""
    accessed = f"Accessed {date.today().strftime('%d %b. %Y')}."
    url = f"{source.url}. " if not source.doi else f"https://doi.org/{source.doi}. "
    return f"{lead}{title}{venue}{year}{url}{accessed}".strip()


def format_citation(source, fmt: str) -> str:
    fmt = (fmt or "apa").lower()
    if fmt == "bibtex":
        return format_bibtex(source)
    if fmt == "mla":
        return format_mla(source)
    return format_apa(source)


def format_all(sources, fmt: str) -> str:
    sep = "\n\n" if fmt == "bibtex" else "\n\n"
    return sep.join(format_citation(s, fmt) for s in sources)
