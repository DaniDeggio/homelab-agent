import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from registry.base import BaseToolRegistry
from registry.search_content import (
    extract_key_points,
    fetch_webpage_content,
    get_tldr,
)

# Import new modules
from registry.search_providers import (
    search_ddgs_library,
    search_duckduckgo_api,
    search_duckduckgo_html,
    search_searxng_api,
)
from registry.search_ranking import rank_search_results

logger = logging.getLogger("web_search_registry")

_MAX_FETCH_PAGES = 5
_MAX_CONTENT_CHARS = 3000
_MAX_WORKERS = 4

# Keywords that signal the query is about news/current events
_NEWS_KEYWORDS = [
    "news", "notizie", "latest", "ultime", "ultima", "ultimo", "aggiornamenti",
    "aggiornate", "recenti", "recent", "updates", "breaking", "launched",
    "launch", "status", "partita", "partito",
]

def _is_news_query(query: str) -> bool:
    q_lc = query.lower()
    return any(kw in q_lc for kw in _NEWS_KEYWORDS)

def _simplify_query(query: str) -> str:
    noise = [
        "latest", "recent", "new", "current", "breaking",
        "news", "updates", "status", "information",
        "ultime", "ultima", "ultimo", "notizie", "aggiornamenti",
        "informazioni", "recenti", "aggiornate",
        "launched", "launch", "partita", "partito",
        "mission", "missione", "date", "details",
        "and", "the", "about", "sulle", "sugli", "sullo", "sulla",
        "dammi", "give", "me", "informazioni",
    ]
    words = query.split()
    cleaned = [w for w in words if w.lower() not in noise]
    result = " ".join(cleaned).strip()
    return result if len(result) > 2 else query

def _search_with_fallback(query: str, count: int = 8, time_filter: Optional[str] = None) -> List[Dict[str, str]]:
    """Search with multi-tier provider fallback chain."""
    is_news = _is_news_query(query)

    # 1. Primary: SearXNG (if available and configured)
    logger.info(f"Trying SearXNG for: {query}")
    results = search_searxng_api(query, count=count, time_filter=time_filter)
    if results:
        return results

    # Small delay
    time.sleep(1.0)

    # 2. Fallback: DDGS Library
    logger.info(f"Trying DDGS library for: {query}")
    results = search_ddgs_library(query, count=count, time_filter=time_filter)
    if results:
        return results

    # 3. Fallback: DDG HTML scraping
    time.sleep(1.0)
    logger.info("Trying DDG HTML fallback")
    results = search_duckduckgo_html(query, count=count)
    if results:
        return results

    # 4. Query reformulation
    simplified = _simplify_query(query)
    if simplified.lower() != query.lower() and len(simplified) > 2:
        logger.info(f"Retrying with simplified query: '{simplified}'")
        time.sleep(1.0)
        results = search_searxng_api(simplified, count=count)
        if results: return results
        time.sleep(0.5)
        results = search_ddgs_library(simplified, count=count)
        if results: return results
        time.sleep(0.5)
        results = search_duckduckgo_html(simplified, count=count)
        if results: return results

    # 5. Last resort: DDG API
    logger.info("All search methods failed, trying DDG Instant Answer API")
    return search_duckduckgo_api(query)


class WebSearchRegistry(BaseToolRegistry):
    @property
    def name(self) -> str:
        return "web"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "web_search",
                "description": (
                    "Esegue una ricerca web completa (Google, Bing, DDG tramite SearXNG): "
                    "scarica il contenuto delle pagine trovate, estrae tabelle, liste e testo "
                    "restituendo un report strutturato e classificato per rilevanza. "
                    "NON aggiungere anni passati nella query a meno che l'utente non lo richieda esplicitamente."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "La query di ricerca da inviare al motore. Deve essere concisa e naturale."
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

        search_results = _search_with_fallback(query, count=10)

        if not search_results:
            return {"query": query, "result": f"Nessun risultato trovato per '{query}'."}

        # Rank results
        ranked_results = rank_search_results(query, search_results)

        sources = [{"url": r["url"], "title": r["title"]} for r in ranked_results if r.get("url")]

        # Fetch top N pages
        urls_to_fetch = [r["url"] for r in ranked_results[:_MAX_FETCH_PAGES] if r.get("url")]
        url_to_index = {r["url"]: i for i, r in enumerate(ranked_results, 1) if r.get("url")}

        fetched_content: List[Dict[str, Any]] = []
        if urls_to_fetch:
            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
                future_to_url = {
                    executor.submit(fetch_webpage_content, url): url
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

        # Format output
        output_parts = []
        output_parts.append("=" * 60)
        output_parts.append("WEB SEARCH RESULTS AND FETCHED CONTENT")
        output_parts.append(f"Query: {query}")
        output_parts.append(f"Found {len(ranked_results)} results, fetched {len(fetched_content)} pages")
        output_parts.append("=" * 60)
        output_parts.append("")

        output_parts.append("SEARCH RESULTS SUMMARY:")
        output_parts.append("-" * 40)
        for i, result in enumerate(ranked_results[:10], 1):
            output_parts.append(f"\n[{i}] {result['title']}")
            output_parts.append(f"    URL: {result['url']}")
            if result.get("snippet"):
                output_parts.append(f"    Snippet: {result['snippet'][:250]}")

        if fetched_content:
            output_parts.append("\n" + "=" * 60)
            output_parts.append("FETCHED PAGE CONTENT:")
            output_parts.append("-" * 40)

            for content in fetched_content:
                idx = content.get("source_index", "?")
                output_parts.append(f"\n[CONTENT {idx}] From: {content['url']}")
                output_parts.append(f"Title: {content['title']}")
                output_parts.append("-" * 30)

                # Summary (TL;DR)
                tldr = get_tldr(content["content"])
                if tldr and len(tldr) > 30:
                    output_parts.append(f"TL;DR: {tldr[:500]}\n")

                # Tables
                if content.get("tables"):
                    output_parts.append("Tables Found:")
                    for table in content["tables"][:3]: # Limit to first 3 tables
                        for row in table[:10]: # Limit to first 10 rows
                            output_parts.append(" | ".join(row))
                        if len(table) > 10:
                            output_parts.append(" ... [more rows truncated]")
                        output_parts.append("")

                # Lists
                if content.get("lists"):
                    output_parts.append("Lists Found:")
                    for lst in content["lists"][:3]:
                        for item in lst[:5]:
                            output_parts.append(f"- {item}")
                        if len(lst) > 5:
                            output_parts.append("- ...")
                        output_parts.append("")

                # Text Content
                text = content["content"][:_MAX_CONTENT_CHARS]
                if len(content["content"]) > _MAX_CONTENT_CHARS:
                    text += "... [truncated]"
                output_parts.append("Main Text:")
                output_parts.append(text)

                key_points = extract_key_points(content["content"])
                if key_points:
                    output_parts.append("\nKey Points:")
                    for pt in key_points:
                        output_parts.append(f"- {pt}")

                output_parts.append("")

        output_parts.append("=" * 60)
        output_parts.append("END OF WEB SEARCH RESULTS")
        output_parts.append("=" * 60)

        output_parts.append(
            "\nIMPORTANT INSTRUCTIONS:\n"
            "1. Use the above web search results and fetched content to answer the user's question\n"
            "2. Prioritize information from the FETCHED PAGE CONTENT section as it contains actual page data\n"
            "3. Cross-reference multiple sources when possible\n"
            "4. Pay special attention to Tables and Lists for structured comparison queries\n"
            "5. If the information is time-sensitive, pay attention to the dates\n"
            "6. Be explicit if the search results don't contain sufficient information"
        )

        result_text = "\n".join(output_parts)
        sources_json = json.dumps(sources, ensure_ascii=False)
        result_text += f"\n\n<!-- SOURCES:{sources_json} -->"

        return {"query": query, "result": result_text}
