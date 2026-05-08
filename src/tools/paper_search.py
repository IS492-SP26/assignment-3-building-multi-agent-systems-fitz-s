"""
Paper Search Tool
Cascading academic search: Semantic Scholar -> arXiv -> OpenAlex -> Tavily(academic).

Created: 2026-05-07
Last reused or audited: 2026-05-07 (Fix 4: Tavily academic-site fallback when SS+arXiv+OpenAlex all return empty due to bursty rate limits)
Authority basis: Plan §Tools, assignment-3 Phase 1 spec; Round-3 fix bundle (Fix 1); Round-5 fix bundle (Fix 4).

Provides paper_search() (AutoGen tool) and paper_search_structured() (citation pipeline).
- Tries Semantic Scholar first (highest-quality metadata, citation counts).
- Falls back to arXiv (Atom XML, no auth, no rate limit) on empty/429/5xx.
- Falls back to OpenAlex (JSON, no auth) if both above empty.
- Final fallback: Tavily web search restricted to academic sites (arxiv.org,
  dl.acm.org, openreview.net, semanticscholar.org) when all three return empty.
- Combines results from any provider that returned, dedupes by lowercased title prefix.
- Each result tagged with source_provider so callers can see which API answered.
"""

from typing import List, Dict, Any, Optional
import os
import logging

logger = logging.getLogger("tools.paper_search")

_SS_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
_SS_FIELDS = "title,authors,year,abstract,venue,url,citationCount"
_ARXIV_BASE = "http://export.arxiv.org/api/query"
_OPENALEX_BASE = "https://api.openalex.org/works"

_REQUEST_TIMEOUT = 10  # seconds per provider


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def paper_search_structured(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    Search academic sources with cascading fallbacks and return structured results.

    arXiv times out on long queries; truncate at 380 chars at the boundary.

    Returns:
        List of dicts with keys: title, authors, year, abstract, venue, url,
        citation_count, source_provider.
    """
    if query and len(query) > 380:
        query = query[:380]
    combined: List[Dict[str, Any]] = []

    # 1) Semantic Scholar
    ss = _semantic_scholar_search(query, max_results)
    if ss:
        combined.extend(ss)

    # 2) arXiv fallback if SS gave us nothing
    if not combined:
        ax = _arxiv_search(query, max_results)
        if ax:
            combined.extend(ax)

    # 3) OpenAlex fallback if still empty
    if not combined:
        oa = _openalex_search(query, max_results)
        if oa:
            combined.extend(oa)

    # 4) Fix 4 (2026-05-07): Tavily academic-site fallback when all three
    # academic providers rate-limited or returned empty. Marked as
    # source_provider="tavily-academic" so callers know it's web-derived.
    if not combined:
        tv = _tavily_academic_fallback(query, max_results)
        if tv:
            combined.extend(tv)
            logger.warning(
                "paper_search: all academic providers empty; using Tavily academic-site fallback (n=%d)",
                len(tv),
            )

    # Dedupe by lowercased title prefix (first 60 chars)
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for p in combined:
        key = (p.get("title") or "").strip().lower()[:60]
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(p)

    # Sort: prefer items with citation counts (SS), then by year desc
    deduped.sort(key=lambda p: (-(p.get("citation_count") or 0), -(p.get("year") or 0)))
    return deduped[:max_results]


def paper_search(query: str, max_results: int = 10) -> str:
    """
    Synchronous academic paper search for AutoGen tool integration.

    Returns markdown-formatted string with paper results.
    """
    results = paper_search_structured(query, max_results)

    if not results:
        return f"No academic papers found for '{query}'."

    providers = sorted({p.get("source_provider", "?") for p in results})
    lines = [f'### Academic papers for "{query}" (n={len(results)}, sources: {", ".join(providers)})']

    for i, p in enumerate(results, 1):
        authors_str = ", ".join((p.get("authors") or [])[:3])
        if len(p.get("authors") or []) > 3:
            authors_str += " et al."

        lines.append(f"\n{i}. **{p['title']}** ({p.get('year') or 'n.d.'})")
        lines.append(f"   Authors: {authors_str or 'Unknown'}")
        if p.get("venue"):
            lines.append(f"   Venue: {p['venue']}")
        lines.append(f"   Citations: {p.get('citation_count') or 0}")
        lines.append(f"   Source: {p.get('source_provider', '?')}")
        if p.get("abstract"):
            abstract = p["abstract"]
            if len(abstract) > 300:
                abstract = abstract[:300] + "..."
            lines.append(f"   Abstract: {abstract}")
        if p.get("url"):
            lines.append(f"   URL: {p['url']}")

    return "\n".join(lines)


class PaperSearchTool:
    """Compatibility shim for imports expecting the old class-based API."""
    def __init__(self, max_results: int = 10):
        self.max_results = max_results

    def search_sync(self, query: str) -> List[Dict[str, Any]]:
        return paper_search_structured(query, self.max_results)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def _semantic_scholar_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    try:
        import requests

        params = {"query": query, "limit": max_results, "fields": _SS_FIELDS}
        headers: Dict[str, str] = {}
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        if api_key:
            headers["x-api-key"] = api_key

        resp = requests.get(_SS_BASE, params=params, headers=headers, timeout=_REQUEST_TIMEOUT)
        if resp.status_code in (429, 500, 502, 503, 504):
            logger.warning("Semantic Scholar returned %s — falling back", resp.status_code)
            return []
        resp.raise_for_status()
        data = resp.json()

        papers: List[Dict[str, Any]] = []
        for item in data.get("data", []):
            authors = [a.get("name", "") for a in (item.get("authors") or [])]
            papers.append({
                "title": item.get("title") or "",
                "authors": authors,
                "year": item.get("year"),
                "abstract": item.get("abstract") or "",
                "venue": item.get("venue") or "",
                "url": item.get("url") or "",
                "citation_count": item.get("citationCount") or 0,
                "source_provider": "semantic_scholar",
            })

        papers.sort(key=lambda p: p["citation_count"], reverse=True)
        return papers

    except Exception as exc:  # noqa: BLE001
        logger.warning("Semantic Scholar search failed: %s", exc)
        return []


def _arxiv_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Query arXiv via the public Atom API. No auth, no rate limit."""
    try:
        import requests
        import xml.etree.ElementTree as ET

        params = {
            "search_query": f"all:{query}",
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        resp = requests.get(_ARXIV_BASE, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()

        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.text)

        papers: List[Dict[str, Any]] = []
        for entry in root.findall("a:entry", ns):
            title_el = entry.find("a:title", ns)
            summary_el = entry.find("a:summary", ns)
            published_el = entry.find("a:published", ns)
            link_el = entry.find("a:id", ns)

            authors = []
            for author in entry.findall("a:author", ns):
                name_el = author.find("a:name", ns)
                if name_el is not None and name_el.text:
                    authors.append(name_el.text.strip())

            year = None
            if published_el is not None and published_el.text:
                try:
                    year = int(published_el.text[:4])
                except (ValueError, TypeError):
                    year = None

            papers.append({
                "title": (title_el.text or "").strip().replace("\n", " ") if title_el is not None else "",
                "authors": authors,
                "year": year,
                "abstract": (summary_el.text or "").strip() if summary_el is not None else "",
                "venue": "arXiv",
                "url": (link_el.text or "").strip() if link_el is not None else "",
                "citation_count": 0,  # arXiv doesn't provide
                "source_provider": "arxiv",
            })
        return papers

    except Exception as exc:  # noqa: BLE001
        logger.warning("arXiv search failed: %s", exc)
        return []


def _openalex_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Query OpenAlex (free, generous limits, no auth)."""
    try:
        import requests

        # No type filter — pipe syntax causes 400; searching without filter
        # returns all work types which is acceptable for academic search.
        params = {
            "search": query,
            "per_page": max_results,
        }
        resp = requests.get(_OPENALEX_BASE, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        papers: List[Dict[str, Any]] = []
        for item in data.get("results", []):
            authorships = item.get("authorships") or []
            authors = [
                (a.get("author") or {}).get("display_name", "")
                for a in authorships
                if (a.get("author") or {}).get("display_name")
            ]

            # Pick the best URL (OA pdf, doi, or landing)
            url = ""
            best_oa = item.get("best_oa_location") or {}
            if best_oa.get("pdf_url"):
                url = best_oa["pdf_url"]
            elif best_oa.get("landing_page_url"):
                url = best_oa["landing_page_url"]
            elif item.get("doi"):
                url = item["doi"]
            elif item.get("id"):
                url = item["id"]

            # Venue: primary_location.source.display_name
            venue = ""
            primary_loc = item.get("primary_location") or {}
            src = primary_loc.get("source") or {}
            if src.get("display_name"):
                venue = src["display_name"]

            papers.append({
                "title": item.get("display_name") or item.get("title") or "",
                "authors": authors,
                "year": item.get("publication_year"),
                "abstract": _reconstruct_openalex_abstract(item.get("abstract_inverted_index")),
                "venue": venue,
                "url": url,
                "citation_count": item.get("cited_by_count") or 0,
                "source_provider": "openalex",
            })
        return papers

    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenAlex search failed: %s", exc)
        return []


def _reconstruct_openalex_abstract(idx: Optional[Dict[str, List[int]]]) -> str:
    """OpenAlex stores abstracts as {word: [positions]}. Reconstruct linear text."""
    if not idx:
        return ""
    pairs: List[tuple] = []
    for word, positions in idx.items():
        for p in positions:
            pairs.append((p, word))
    pairs.sort(key=lambda x: x[0])
    return " ".join(w for _, w in pairs)


def _tavily_academic_fallback(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Fix 4 (2026-05-07): Final fallback when SS / arXiv / OpenAlex all return
    empty due to bursty rate limits. Reuses the project's Tavily web client
    with site:arxiv.org / dl.acm.org / openreview.net / semanticscholar.org
    bias so results are still academic-flavoured. Returned items are tagged
    source_provider='tavily-academic' so the registry can flag them.
    """
    try:
        from src.tools.web_search import web_search_structured  # reuse Tavily client
    except ImportError:
        return []
    enriched = (
        f"{query} site:arxiv.org OR site:dl.acm.org OR "
        "site:openreview.net OR site:semanticscholar.org"
    )
    try:
        web_results = web_search_structured(enriched, max_results)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tavily academic fallback failed: %s", exc)
        return []
    out: List[Dict[str, Any]] = []
    for r in web_results or []:
        out.append({
            "title": r.get("title", "") or "",
            "authors": [],  # Tavily doesn't give authors
            "year": "",
            "abstract": r.get("snippet", "") or "",
            "venue": r.get("source_provider", "") or "",
            "url": r.get("url", "") or "",
            "citation_count": 0,
            "source_provider": "tavily-academic",
        })
    return out
