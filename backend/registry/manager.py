import sys
import os
import logging
from typing import List, Dict, Any, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from registry.base import BaseToolRegistry
from registry.metamcp import MetaMCPRegistry
from registry.web_search import WebSearchRegistry
from registry.code_exec import CodeExecRegistry

logger = logging.getLogger("registry_manager")

class ToolRegistryManager:
    def __init__(self):
        self._registries: Dict[str, BaseToolRegistry] = {}
        # Registra i tre registry ufficiali
        self.register_registry(MetaMCPRegistry())
        self.register_registry(WebSearchRegistry())
        self.register_registry(CodeExecRegistry())

    def register_registry(self, registry: BaseToolRegistry):
        self._registries[registry.name] = registry
        logger.info(f"Tool registry registrato: '{registry.name}'")

    def get_tools_for_mode(self, allowed_registries: List[str]) -> List[Dict[str, Any]]:
        """Restituisce la lista di tool aggregati per i soli registry consentiti."""
        tools = []
        for reg_name in allowed_registries:
            reg = self._registries.get(reg_name)
            if reg:
                try:
                    tlist = reg.get_tools()
                    if tlist:
                        tools.extend(tlist)
                except Exception as e:
                    logger.warning(f"Errore nel recupero tool per registry '{reg_name}': {e}")
        return tools

    def execute_tool(self, tool_name: str, args: Dict[str, Any], allowed_registries: List[str]) -> Any:
        """Individua il registry che possiede il tool ed esegue l'azione se consentito."""
        for reg_name in allowed_registries:
            reg = self._registries.get(reg_name)
            if not reg:
                continue
            
            reg_tools = reg.get_tools()
            tool_names = [t.get("name") for t in reg_tools if isinstance(t, dict)]
            if tool_name in tool_names:
                logger.info(f"Esecuzione tool '{tool_name}' tramite registry '{reg_name}'")
                return reg.execute_tool(tool_name, args)

        return {"error": f"Tool '{tool_name}' non trovato o non consentito nei registry: {allowed_registries}"}

_global_manager = ToolRegistryManager()

def get_registry_manager() -> ToolRegistryManager:
    return _global_manager
