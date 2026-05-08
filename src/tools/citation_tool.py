"""
Citation Tool
Manages a source registry and formats APA citations.

Created: 2026-05-07
Last reused or audited: 2026-05-07
Authority basis: Plan §Tools, assignment-3 Phase 1 spec

SourceRegistry: idempotent add (URL-keyed), APA formatting, provenance verification.
format_sources_for_writer(): markdown bullet list for Writer agent context.
"""

from typing import Dict, Any, List, Optional
import re


class SourceRegistry:
    """
    Tracks sources by assigned ID (S1, S2, ...).
    Idempotent on URL match — same URL returns existing ID.
    """

    def __init__(self) -> None:
        self._sources: dict[str, dict] = {}  # id -> source dict
        self._url_index: dict[str, str] = {}  # url -> id
        self._counter = 0

    def add(self, source: dict) -> str:
        """
        Add a source dict, return assigned ID like 'S1'.
        Idempotent on URL match: if the URL is already registered, returns existing ID.
        """
        url = source.get("url", "")
        if url and url in self._url_index:
            return self._url_index[url]

        self._counter += 1
        sid = f"S{self._counter}"
        entry = dict(source)
        entry["_id"] = sid
        self._sources[sid] = entry
        if url:
            self._url_index[url] = sid
        return sid

    def get(self, source_id: str) -> Optional[dict]:
        return self._sources.get(source_id)

    def all(self) -> List[dict]:
        return list(self._sources.values())

    def format_apa(self, source_id: str) -> str:
        """APA-style citation. 'Author, A. (Year). Title. Venue.'"""
        source = self._sources.get(source_id)
        if not source:
            return f"[{source_id}: not found]"

        authors = source.get("authors") or []
        year = source.get("year", "n.d.")
        title = source.get("title", "Untitled")
        venue = source.get("venue", "")
        url = source.get("url", "")

        # Format authors APA style
        if authors:
            formatted = []
            for name in authors:
                if not name:
                    continue
                if "," in name:
                    formatted.append(name)
                else:
                    parts = name.strip().split()
                    if len(parts) >= 2:
                        surname = parts[-1]
                        initials = ". ".join(p[0].upper() for p in parts[:-1] if p) + "."
                        formatted.append(f"{surname}, {initials}")
                    else:
                        formatted.append(name)

            if len(formatted) == 1:
                author_str = formatted[0]
            elif len(formatted) == 2:
                author_str = f"{formatted[0]}, & {formatted[1]}"
            else:
                author_str = f"{formatted[0]}, et al."
        else:
            author_str = "Unknown Author"

        citation = f"{author_str} ({year}). {title}."
        if venue:
            citation += f" {venue}."
        if url:
            citation += f" {url}"
        return citation

    def as_dict(self) -> dict[str, dict]:
        """Full registry for serialization (UI / JSON export)."""
        return dict(self._sources)

    def find_missing(self, text: str) -> List[str]:
        """Return list of [S\\d+] IDs referenced in text that are NOT in this registry."""
        referenced = re.findall(r'\[S(\d+)\]', text)
        return [f"S{n}" for n in referenced if f"S{n}" not in self._sources]


# Compatibility alias for imports expecting the old class name
CitationTool = SourceRegistry


def format_sources_for_writer(registry: SourceRegistry) -> str:
    """
    Produce a markdown bullet list of all sources with their IDs,
    suitable for a Writer agent to receive in context.
    """
    sources = registry.all()
    if not sources:
        return "_No sources registered._"

    lines = ["**Sources:**"]
    for s in sources:
        sid = s.get("_id", "?")
        title = s.get("title", "Untitled")
        url = s.get("url", "")
        year = s.get("year", "n.d.")
        line = f"- [{sid}] {title} ({year})"
        if url:
            line += f" — {url}"
        lines.append(line)
    return "\n".join(lines)
