import sys
import os
import json
import time
import logging
from typing import List, Dict, Any, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from registry.base import BaseToolRegistry
from registry.metamcp import MetaMCPRegistry
from registry.web_search import WebSearchRegistry
from registry.code_exec import CodeExecRegistry
import guardrails
import audit_log

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

    def execute_tool(self, tool_name: str, args: Dict[str, Any], allowed_registries: List[str],
                     thread_id: Optional[str] = None, mode: Optional[str] = None) -> Any:
        """Individua il registry che possiede il tool, applica i guardrail, esegue e registra l'audit."""
        start_ms = time.monotonic() * 1000

        for reg_name in allowed_registries:
            reg = self._registries.get(reg_name)
            if not reg:
                continue
            
            reg_tools = reg.get_tools()
            tool_names = [t.get("name") for t in reg_tools if isinstance(t, dict)]
            if tool_name in tool_names:
                # --- Guardrail (Fase 0.3) ---
                block_reason = guardrails.enforce_guardrails(tool_name, args)
                if block_reason:
                    audit_log.log_tool_call(
                        tool_name, args, thread_id=thread_id, mode=mode,
                        registry=reg_name, result={"blocked": block_reason},
                        is_error=True, duration_ms=0,
                    )
                    return {"error": block_reason, "blocked_by_guardrail": True}

                logger.info(f"Esecuzione tool '{tool_name}' tramite registry '{reg_name}'")
                try:
                    result = reg.execute_tool(tool_name, args)
                except Exception as e:
                    result = {"error": str(e)}

                duration_ms = int(time.monotonic() * 1000 - start_ms)
                is_error = isinstance(result, dict) and bool(result.get("error"))
                # --- Audit log (Fase 0.4) ---
                audit_log.log_tool_call(
                    tool_name, args, thread_id=thread_id, mode=mode,
                    registry=reg_name, result=result,
                    is_error=is_error, duration_ms=duration_ms,
                )
                return result

        return {"error": f"Tool '{tool_name}' non trovato o non consentito nei registry: {allowed_registries}"}

_global_manager = ToolRegistryManager()

def get_registry_manager() -> ToolRegistryManager:
    return _global_manager
