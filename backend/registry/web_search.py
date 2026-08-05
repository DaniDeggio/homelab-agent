import sys
import os
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
        
        try:
            # Semplice ricerca via API pubblica DuckDuckGo Instant Answer o html lite fallback
            url = f"https://api.duckduckgo.com/?q={requests.utils.quote(query)}&format=json&no_html=1&skip_disambig=1"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                abstract = data.get("AbstractText", "")
                heading = data.get("Heading", "")
                related = [t.get("Text") for t in data.get("RelatedTopics", []) if isinstance(t, dict) and t.get("Text")]
                
                results_text = ""
                if abstract:
                    results_text += f"**{heading}**: {abstract}\n\n"
                if related:
                    results_text += "**Risultati correlati:**\n- " + "\n- ".join(related[:5])
                
                if not results_text.strip():
                    results_text = f"Nessun estratto diretto trovato per '{query}'. Chiamata completata."

                return {"query": query, "result": results_text}
            else:
                return {"error": f"Errore HTTP nella ricerca web: {res.status_code}"}
        except Exception as e:
            logger.warning(f"Chiamata web_search fallita: {e}")
            return {"error": f"Eccezione durante la ricerca web: {str(e)}"}
