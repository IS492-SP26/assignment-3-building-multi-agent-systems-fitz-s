"""
Web Search Tool
Cascading web search: Tavily -> DuckDuckGo HTML scrape.

Created: 2026-05-07
Last reused or audited: 2026-05-08 (Path C Fix 3: added BLOG_AGGREGATOR_DOMAINS
blocklist. emergentmind.com / themoonlight.io etc. were 20% of evidence pool,
producing 4th-hand synthesis (Qwen summarizes blog summary of paper summary).
Filter applied to BOTH Tavily and DDG result paths; arxiv/openreview kept.)
Authority basis: Plan §Tools, assignment-3 Phase 1 spec; Round-3 fix bundle (Fix 2);
critic_report_v2 finding 3.3.

Provides web_search() (AutoGen tool) and web_search_structured() (citation pipeline).
Never logs API key values.
"""

from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
import os
import logging

from src.utils.secrets import inject_into_env

# Inject Tavily key from Keychain on import
inject_into_env("skill_tavily_api_key", "TAVILY_API_KEY")

logger = logging.getLogger("tools.web_search")


# Critic-v2 fix: blog/SEO aggregators that summarize papers (4th-hand synthesis).
# These pollute the evidence pool with low-quality re-summaries of primary work.
# Note: arxiv.org / acm.org / openreview.net / semanticscholar.org are KEPT.
BLOG_AGGREGATOR_DOMAINS = {
    "emergentmind.com", "themoonlight.io", "deepai.org",
    "promptengineering.org", "marktechpost.com", "synthesis.ai",
    "aimagazine.com", "venturebeat.com",  # business news, not research
}


def _filter_blog_aggregators(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop results whose hostname is in BLOG_AGGREGATOR_DOMAINS.

    Path C Fix 3 (2026-05-08): protects evidence pool from low-tier
    re-summarizers. Logs blocked count so we can see if filter is too aggressive.
    """
    out: List[Dict[str, Any]] = []
    blocked = 0
    for r in results:
        url = r.get("url") or ""
        try:
            host = urlparse(url).hostname or ""
            host = host.lower()
            if host.startswith("www."):
                host = host[4:]
        except Exception:
            host = ""
        if host in BLOG_AGGREGATOR_DOMAINS:
            blocked += 1
            continue
        out.append(r)
    if blocked > 0:
        logger.info("web_search: filtered %d blog aggregator results", blocked)
    return out


def web_search_structured(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Search the web with cascading fallbacks and return structured results.

    Order:
      1. Tavily (if TAVILY_API_KEY present and quota intact).
      2. DuckDuckGo HTML scrape (no auth, no quota).

    Tavily rejects queries >400 chars; arXiv times out on long queries. Truncate
    to 380 chars at the search-tool boundary so callers can pass long
    sub-question prose without hitting backend limits.
    """
    if query and len(query) > 380:
        query = query[:380]
    return _web_search_structured_impl(query, max_results)


def _web_search_structured_impl(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Original implementation — separated so the public function can pre-truncate.

    Returns:
        List of dicts with keys: title, url, snippet, published_date, source_provider.

    Path C Fix 3 (2026-05-08): every provider's results now pass through
    _filter_blog_aggregators before return. Critical that ALL provider paths
    apply the filter — bypass would re-introduce 4th-hand summaries.
    """
    # Try Tavily first
    if os.getenv("TAVILY_API_KEY"):
        results = _tavily_search(query, max_results)
        results = _filter_blog_aggregators(results)
        if results:
            return results
        logger.info("Tavily returned 0 usable results — falling back to DuckDuckGo")

    # Fallback: DDG HTML scrape (POST form)
    ddg_results = _ddg_html_search(query, max_results)
    return _filter_blog_aggregators(ddg_results)


def web_search(query: str, max_results: int = 5) -> str:
    """Synchronous web search for AutoGen tool integration."""
    results = web_search_structured(query, max_results)

    if not results:
        return f"No web search results found for '{query}'."

    provider = results[0].get("source_provider", "unknown") if results else "unknown"
    lines = [f'### Web search results for "{query}" (provider: {provider}, n={len(results)})']

    for i, r in enumerate(results, 1):
        lines.append(f"\n{i}. **{r.get('title', 'No title')}**")
        lines.append(f"   URL: {r.get('url', '')}")
        lines.append(f"   Snippet: {r.get('snippet', '')}")
        if r.get("published_date"):
            lines.append(f"   Published: {r['published_date']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def _tavily_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
        response = client.search(query, max_results=max_results, search_depth="advanced")
        results = []
        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "published_date": item.get("published_date"),
                "source_provider": "tavily",
            })
        return results
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tavily search failed, will fall back to DuckDuckGo: %s", exc)
        return []


class WebSearchTool:
    """Compatibility shim for imports expecting the old class-based API."""
    def __init__(self, provider: str = "tavily", max_results: int = 5):
        self.provider = provider
        self.max_results = max_results

    def search_sync(self, query: str) -> List[Dict[str, Any]]:
        return web_search_structured(query, self.max_results)


def _ddg_html_search(query: str, n: int = 5) -> List[Dict[str, Any]]:
    """Scrape DuckDuckGo's no-JS HTML results page via POST form.

    Returns list of {title, url, snippet, published_date, source_provider}.
    Returns [] on any failure (caller treats empty as authoritative no-results).
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import urlparse, parse_qs, unquote
    except ImportError:
        logger.error("DuckDuckGo fallback unavailable: requests/bs4 not installed")
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        ),
    }
    try:
        r = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=headers,
            timeout=12,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        results: List[Dict[str, Any]] = []
        for div in soup.select(".result")[:n]:
            a = div.select_one(".result__a")
            snippet = div.select_one(".result__snippet")
            if not a or not a.get("href"):
                continue
            url = a.get("href")
            # DDG uses redirect URLs — extract the real one from the uddg query param
            if "duckduckgo.com/l/" in url or url.startswith("//duckduckgo.com/l/") or url.startswith("/l/"):
                qs = parse_qs(urlparse(url).query)
                url = unquote(qs.get("uddg", [url])[0])
            results.append({
                "title": a.get_text(" ", strip=True),
                "url": url,
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                "published_date": "",
                "source_provider": "duckduckgo",
            })
        return results
    except Exception as exc:  # noqa: BLE001
        logger.error("DuckDuckGo HTML search failed: %s", exc)
        return []


# Keep _ddg_search as a backward-compat alias for any caller that still uses it.
_ddg_search = _ddg_html_search
