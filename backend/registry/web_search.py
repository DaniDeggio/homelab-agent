import sys
import os
import re
import html
import json
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import quote, urlparse, parse_qs, urljoin

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from registry.base import BaseToolRegistry

logger = logging.getLogger("web_search_registry")

# ── Constants ──
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_SEARCH_TIMEOUT = 10
_FETCH_TIMEOUT = 12
_MAX_FETCH_PAGES = 3
_MAX_CONTENT_CHARS = 3000
_MAX_WORKERS = 3

# ── Time-filter auto-detection ──
_TIME_HINTS = {
    "day": ["today", "oggi", "right now", "this morning", "adesso", "ultime ore", "breaking"],
    "week": ["this week", "questa settimana", "recent", "recenti", "notizie", "aggiornate", "aggiornamenti",
             "last few days", "ultimi giorni", "news", "latest", "ultime", "ultima", "ultimo"],
    "month": ["this month", "questo mese", "past month", "ultimo mese"],
}

# Keywords that signal the query is about news/current events
_NEWS_KEYWORDS = [
    "news", "notizie", "latest", "ultime", "ultima", "ultimo", "aggiornamenti",
    "aggiornate", "recenti", "recent", "updates", "breaking", "launched",
    "launch", "status", "partita", "partito",
]


def _detect_time_filter(query: str) -> Optional[str]:
    """Auto-detect freshness filter from query keywords."""
    q_lc = query.lower()
    for period, hints in _TIME_HINTS.items():
        if any(h in q_lc for h in hints):
            return period
    return None


def _is_news_query(query: str) -> bool:
    """Detect if the query is likely about news/current events."""
    q_lc = query.lower()
    return any(kw in q_lc for kw in _NEWS_KEYWORDS)


def _simplify_query(query: str) -> str:
    """Strip filler words and freshness hints to create a simpler, broader query."""
    noise = [
        "latest", "recent", "new", "current", "breaking",
        "news", "updates", "status", "information",
        "ultime", "ultima", "ultimo", "notizie", "aggiornamenti",
        "informazioni", "recenti", "aggiornate",
        "launched", "partita", "partito",
    ]
    words = query.split()
    cleaned = [w for w in words if w.lower() not in noise]
    result = " ".join(cleaned).strip()
    return result if len(result) > 3 else query


# ── Lightweight HTML text extractor (no external deps) ──
class _TextExtractor(HTMLParser):
    """Strip HTML tags and extract readable text, skipping script/style/nav/footer."""
    _SKIP_TAGS = {"script", "style", "noscript", "template", "nav", "header", "footer", "aside", "svg"}

    def __init__(self):
        super().__init__()
        self._text_parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str):
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._text_parts.append(text)

    def get_text(self) -> str:
        raw = " ".join(self._text_parts)
        return re.sub(r"\s+", " ", raw).strip()


def _extract_text_from_html(html_content: str) -> str:
    """Extract readable text from HTML without BeautifulSoup."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html_content)
    except Exception:
        pass
    return extractor.get_text()


def _extract_title_from_html(html_content: str) -> str:
    """Extract <title> from HTML."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
    if m:
        return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    return ""


# ── DuckDuckGo redirect resolution ──
def _resolve_ddg_redirect(raw_url: str) -> str:
    """Resolve DDG /l/?uddg=... redirect URLs to actual destinations."""
    if not raw_url:
        return raw_url
    resolved = raw_url
    if resolved.startswith("//"):
        resolved = "https:" + resolved
    elif resolved.startswith("/"):
        resolved = urljoin("https://html.duckduckgo.com", resolved)
    try:
        parsed = urlparse(resolved)
        hostname = (parsed.hostname or "").lower()
        if (hostname == "duckduckgo.com" or hostname.endswith(".duckduckgo.com")) and parsed.path.rstrip("/") == "/l":
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                return qs["uddg"][0]
    except Exception:
        pass
    return resolved


# ── Search Result Extraction ──

def _search_ddgs_library(query: str, count: int = 8, time_filter: Optional[str] = None) -> List[Dict[str, str]]:
    """Search using duckduckgo-search library (primary provider). Bypasses CAPTCHAs."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.warning("duckduckgo-search package not installed; skipping DDGS provider")
        return []

    timelimit = None
    if time_filter:
        time_map = {"day": "d", "week": "w", "month": "m", "year": "y"}
        timelimit = time_map.get(time_filter)

    try:
        ddgs = DDGS()
        raw = ddgs.text(query, max_results=count, timelimit=timelimit)
        results = []
        for item in raw:
            url = item.get("href", "")
            if not url:
                continue
            results.append({
                "title": item.get("title", ""),
                "url": url,
                "snippet": item.get("body", ""),
            })
        logger.info(f"DDGS library returned {len(results)} results for: {query}")
        return results
    except Exception as e:
        logger.warning(f"DDGS library search failed: {e}")
        return []


def _search_ddgs_news(query: str, count: int = 8, time_filter: Optional[str] = None) -> List[Dict[str, str]]:
    """Search using DDGS news endpoint for current events queries."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return []

    timelimit = None
    if time_filter:
        time_map = {"day": "d", "week": "w", "month": "m", "year": "y"}
        timelimit = time_map.get(time_filter)

    try:
        ddgs = DDGS()
        raw = ddgs.news(query, max_results=count, timelimit=timelimit)
        results = []
        for item in raw:
            url = item.get("url", "") or item.get("href", "")
            if not url:
                continue
            results.append({
                "title": item.get("title", ""),
                "url": url,
                "snippet": item.get("body", "") or item.get("excerpt", ""),
            })
        logger.info(f"DDGS news returned {len(results)} results for: {query}")
        return results
    except Exception as e:
        logger.warning(f"DDGS news search failed: {e}")
        return []


def _search_duckduckgo_html(query: str, count: int = 8) -> List[Dict[str, str]]:
    """Fallback: Search DuckDuckGo HTML lite (may get CAPTCHAed from server IPs)."""
    headers = {"User-Agent": _USER_AGENT}
    results = []

    try:
        res = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=headers,
            timeout=_SEARCH_TIMEOUT,
        )
        if res.status_code not in (200, 202):
            logger.warning(f"DDG HTML returned status {res.status_code}")
            return results

        text = res.text
        # Detect CAPTCHA
        if "anomaly-modal" in text or "Select all squares" in text:
            logger.warning("DDG HTML returned CAPTCHA page, skipping")
            return results

        link_pattern = re.compile(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE
        )
        snippet_pattern = re.compile(
            r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE
        )

        links = link_pattern.findall(text)
        snippets = snippet_pattern.findall(text)

        for i, (raw_href, raw_title) in enumerate(links[:count]):
            url = _resolve_ddg_redirect(raw_href)
            try:
                host = urlparse(url).hostname or ""
                if host.endswith("duckduckgo.com") or not host:
                    continue
            except Exception:
                continue

            title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            snippet = ""
            if i < len(snippets):
                snippet = html.unescape(re.sub(r"<[^>]+>", "", snippets[i])).strip()

            if url and title:
                results.append({"title": title, "url": url, "snippet": snippet})

        logger.info(f"DDG HTML returned {len(results)} results")
    except Exception as e:
        logger.warning(f"DDG HTML search error: {e}")

    return results


def _search_duckduckgo_api(query: str) -> List[Dict[str, str]]:
    """Try DuckDuckGo Instant Answer API for quick facts."""
    headers = {"User-Agent": _USER_AGENT}
    results = []
    try:
        url_api = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
        res = requests.get(url_api, headers=headers, timeout=_SEARCH_TIMEOUT)
        if res.status_code in (200, 202):
            data = res.json()
            abstract = data.get("AbstractText", "")
            heading = data.get("Heading", "")
            abstract_url = data.get("AbstractURL", "")
            if abstract and len(abstract) > 30:
                results.append({
                    "title": heading or "DuckDuckGo Abstract",
                    "url": abstract_url or "",
                    "snippet": abstract[:500],
                })
    except Exception as e:
        logger.debug(f"DDG API error (non-critical): {e}")
    return results


def _search_with_fallback(query: str, count: int = 8, time_filter: Optional[str] = None) -> List[Dict[str, str]]:
    """Search with multi-tier provider fallback chain and automatic query reformulation.
    
    Chain:
    1. DDGS text (with time_filter)
    2. DDGS text (without time_filter, if applicable)
    3. DDGS news (for news-like queries)
    4. DDG HTML scraping
    5. Simplified query via DDGS text (strip noise words)
    6. DDG Instant Answer API
    """
    is_news = _is_news_query(query)

    # 1. Primary: DDGS library with time_filter
    results = _search_ddgs_library(query, count=count, time_filter=time_filter)
    if results:
        return results

    # 2. Retry without time_filter
    if time_filter:
        logger.info(f"DDGS library returned 0 results with time_filter='{time_filter}', retrying without time limit")
        results = _search_ddgs_library(query, count=count, time_filter=None)
        if results:
            return results

    # 3. Try DDGS news endpoint for news-like queries
    if is_news:
        logger.info(f"Trying DDGS news endpoint for: {query}")
        results = _search_ddgs_news(query, count=count, time_filter=time_filter)
        if results:
            return results
        if time_filter:
            results = _search_ddgs_news(query, count=count, time_filter=None)
            if results:
                return results

    # 4. Fallback: DDG HTML scraping
    logger.info("DDGS library returned 0 results, trying DDG HTML fallback")
    results = _search_duckduckgo_html(query, count=count)
    if results:
        return results

    # 5. Query reformulation: simplify the query and retry
    simplified = _simplify_query(query)
    if simplified != query and len(simplified) > 3:
        logger.info(f"Retrying with simplified query: '{simplified}' (original: '{query}')")
        results = _search_ddgs_library(simplified, count=count, time_filter=None)
        if results:
            return results
        # Also try news with simplified query
        if is_news:
            results = _search_ddgs_news(simplified, count=count, time_filter=None)
            if results:
                return results

    # 6. Last resort: DDG Instant Answer API (limited but no CAPTCHA)
    logger.info("All search methods failed, trying DDG Instant Answer API")
    return _search_duckduckgo_api(query)


# ── Page Content Fetching ──
def _fetch_page_content(url: str, timeout: int = _FETCH_TIMEOUT) -> Dict[str, Any]:
    """Fetch a web page and extract its text content."""
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5,it;q=0.3",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
    }
    try:
        res = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if res.status_code >= 400:
            return {"url": url, "title": "", "content": "", "success": False, "error": f"HTTP {res.status_code}"}

        content_type = res.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "text" not in content_type:
            return {"url": url, "title": "", "content": "", "success": False, "error": f"Non-text content: {content_type}"}

        html_text = res.text
        title = _extract_title_from_html(html_text)
        content = _extract_text_from_html(html_text)

        if len(content) < 50:
            return {"url": url, "title": title, "content": content, "success": False, "error": "Too little content"}

        return {"url": url, "title": title, "content": content, "success": True, "error": ""}

    except requests.Timeout:
        return {"url": url, "title": "", "content": "", "success": False, "error": "Timeout"}
    except Exception as e:
        return {"url": url, "title": "", "content": "", "success": False, "error": str(e)}


def _extract_key_points(text: str) -> List[str]:
    """Pull bullet-style key points from text."""
    points = []
    for line in text.splitlines():
        m = re.match(r"^\s*[-*•]\s+(.*)", line) or re.match(r"^\s*\d+[.)]\s+(.*)", line)
        if m:
            points.append(m.group(1).strip())
    return points[:5]


def _get_tldr(text: str, max_sentences: int = 3) -> str:
    """Produce a TL;DR from the first few sentences."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    selected = [s.strip() for s in sentences if s.strip()][:max_sentences]
    return " ".join(selected)


# ── Main Registry ──
class WebSearchRegistry(BaseToolRegistry):
    @property
    def name(self) -> str:
        return "web"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "web_search",
                "description": (
                    "Esegue una ricerca web completa: cerca risultati su DuckDuckGo, "
                    "scarica il contenuto delle pagine trovate e restituisce un report strutturato "
                    "con titoli, URL, snippet e testo estratto dalle pagine. "
                    "NON aggiungere anni passati nella query a meno che l'utente non lo richieda esplicitamente."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "La query di ricerca da inviare al motore di ricerca. Deve essere concisa e naturale."
                        }
                    },
                    "required": ["query"]
                }
            }
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name != "web_search":
            return {"error": f"Tool '{tool_name}' sconosciuto nel registry web."}

        query = args.get("query", "").strip()
        if not query:
            return {"error": "Parametro 'query' mancante."}

        logger.info(f"Starting comprehensive web search for: {query}")

        # Auto-detect time filter
        time_filter = _detect_time_filter(query)
        if time_filter:
            logger.info(f"Auto-detected time filter: {time_filter}")

        # Step 1: Search with provider fallback chain (DDGS lib -> HTML -> API)
        search_results = _search_with_fallback(query, count=8, time_filter=time_filter)

        if not search_results:
            return {"query": query, "result": f"Nessun risultato trovato per '{query}'."}

        # Build sources list for potential frontend display
        sources = [{"url": r["url"], "title": r["title"]} for r in search_results if r.get("url")]

        # Step 2: Fetch content from top pages in parallel
        urls_to_fetch = [r["url"] for r in search_results[:_MAX_FETCH_PAGES] if r.get("url")]
        url_to_index = {r["url"]: i for i, r in enumerate(search_results, 1) if r.get("url")}

        fetched_content: List[Dict[str, Any]] = []
        if urls_to_fetch:
            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
                future_to_url = {
                    executor.submit(_fetch_page_content, url): url
                    for url in urls_to_fetch
                }
                for future in as_completed(future_to_url):
                    url = future_to_url[future]
                    try:
                        result = future.result()
                        if result.get("success") and result.get("content") and len(result["content"]) >= 50:
                            result["source_index"] = url_to_index.get(url, 0)
                            fetched_content.append(result)
                    except Exception as e:
                        logger.warning(f"Exception fetching {url}: {e}")

            fetched_content.sort(key=lambda c: c.get("source_index", 999))
            logger.info(f"Successfully fetched content from {len(fetched_content)} pages")

        # Step 3: Format comprehensive output
        output_parts = []

        # Sources summary
        output_parts.append("=" * 60)
        output_parts.append("WEB SEARCH RESULTS AND FETCHED CONTENT")
        output_parts.append(f"Query: {query}")
        output_parts.append(f"Found {len(search_results)} results, fetched {len(fetched_content)} pages")
        output_parts.append("=" * 60)
        output_parts.append("")

        # Search results summary
        output_parts.append("SEARCH RESULTS SUMMARY:")
        output_parts.append("-" * 40)
        for i, result in enumerate(search_results, 1):
            output_parts.append(f"\n[{i}] {result['title']}")
            output_parts.append(f"    URL: {result['url']}")
            if result.get("snippet"):
                output_parts.append(f"    Snippet: {result['snippet'][:250]}")

        # Fetched page content
        if fetched_content:
            output_parts.append("\n" + "=" * 60)
            output_parts.append("FETCHED PAGE CONTENT:")
            output_parts.append("-" * 40)

            for content in fetched_content:
                idx = content.get("source_index", "?")
                output_parts.append(f"\n[CONTENT {idx}] From: {content['url']}")
                output_parts.append(f"Title: {content['title']}")
                output_parts.append("-" * 30)

                text = content["content"][:_MAX_CONTENT_CHARS]
                if len(content["content"]) > _MAX_CONTENT_CHARS:
                    text += "... [truncated]"
                output_parts.append(text)

                key_points = _extract_key_points(content["content"])
                if key_points:
                    output_parts.append("\nKey Points:")
                    for pt in key_points:
                        output_parts.append(f"- {pt}")

                tldr = _get_tldr(content["content"])
                if tldr and len(tldr) > 30:
                    output_parts.append("\nTL;DR:")
                    output_parts.append(tldr[:500])

                output_parts.append("")

        output_parts.append("=" * 60)
        output_parts.append("END OF WEB SEARCH RESULTS")
        output_parts.append("=" * 60)

        # Instructions for the LLM
        output_parts.append(
            "\nIMPORTANT INSTRUCTIONS:\n"
            "1. Use the above web search results and fetched content to answer the user's question\n"
            "2. Prioritize information from the FETCHED PAGE CONTENT section as it contains actual page data\n"
            "3. Cross-reference multiple sources when possible\n"
            "4. If the information is time-sensitive, pay attention to the dates\n"
            "5. Be explicit if the search results don't contain sufficient information"
        )

        result_text = "\n".join(output_parts)

        # Append sources as metadata for frontend
        sources_json = json.dumps(sources, ensure_ascii=False)
        result_text += f"\n\n<!-- SOURCES:{sources_json} -->"

        return {"query": query, "result": result_text}
