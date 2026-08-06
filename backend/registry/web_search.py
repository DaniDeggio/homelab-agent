import sys
import os
import re
import html
import logging
import requests
from typing import List, Dict, Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from registry.base import BaseToolRegistry

logger = logging.getLogger("web_search_registry")

class WebSearchRegistry(BaseToolRegistry):
    @property
    def name(self) -> str:
        return "web"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "web_search",
                "description": "Esegue una ricerca web per cercare informazioni o documentazione aggiornata.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "La query di ricerca da inviare al motore di ricerca."
                        }
                    },
                    "required": ["query"]
                }
            }
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name != "web_search":
            return {"error": f"Tool '{tool_name}' sconosciuto nel registry web."}
        
        query = args.get("query", "")
        if not query:
            return {"error": "Parametro 'query' mancante."}
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        results_text = ""

        try:
            # 1. Prova DuckDuckGo Instant Answer API
            url_api = f"https://api.duckduckgo.com/?q={requests.utils.quote(query)}&format=json&no_html=1&skip_disambig=1"
            res_api = requests.get(url_api, headers=headers, timeout=8)
            if res_api.status_code in [200, 202]:
                try:
                    data = res_api.json()
                    abstract = data.get("AbstractText", "")
                    heading = data.get("Heading", "")
                    related = [t.get("Text") for t in data.get("RelatedTopics", []) if isinstance(t, dict) and t.get("Text")]
                    
                    if abstract:
                        results_text += f"**{heading}**: {abstract}\n\n"
                    if related:
                        results_text += "**Risultati correlati:**\n- " + "\n- ".join(related[:5]) + "\n\n"
                except Exception:
                    pass

            # 2. Fallback su DuckDuckGo HTML Search se Instant Answer è scarno o vuoto
            if len(results_text.strip()) < 50:
                url_html = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
                res_html = requests.post(url_html, data={"q": query}, headers=headers, timeout=8)
                if res_html.status_code in [200, 202]:
                    text = res_html.text
                    matches = re.findall(r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', text, re.DOTALL | re.IGNORECASE)
                    if not matches:
                        matches = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', text, re.DOTALL | re.IGNORECASE)
                    
                    snippets = []
                    for m in matches:
                        clean = re.sub(r'<[^>]+>', '', m)
                        clean = html.unescape(clean).strip()
                        if clean and clean not in snippets:
                            snippets.append(clean)
                    
                    if snippets:
                        results_text += "**Risultati ricerca web:**\n- " + "\n- ".join(snippets[:5])

            if not results_text.strip():
                results_text = f"Nessun estratto diretto trovato per '{query}'."

            return {"query": query, "result": results_text}

        except Exception as e:
            logger.warning(f"Chiamata web_search fallita per '{query}': {e}")
            return {"error": f"Eccezione durante la ricerca web: {str(e)}"}
