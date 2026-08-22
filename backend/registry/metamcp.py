import sys
import os
from typing import List, Dict, Any

# Assicura che la directory backend sia nell'import path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from registry.base import BaseToolRegistry
from tool_catalog import get_tool_catalog
from mcp_client import MetaMCPClient
import config
import logging

logger = logging.getLogger("metamcp_registry")

try:
    from mcp_sdk_client import MetaMCPSdkClient, _SDK_AVAILABLE
except ImportError:
    _SDK_AVAILABLE = False

class MetaMCPRegistry(BaseToolRegistry):
    def __init__(self):
        self._client = MetaMCPClient(config.METAMCP_URL, api_key=config.METAMCP_API_KEY)
        # Fase 1.2: preferisci SDK ufficiale MCP, fallback al client legacy
        self._sdk_client = None
        if _SDK_AVAILABLE:
            try:
                self._sdk_client = MetaMCPSdkClient(config.METAMCP_URL, api_key=config.METAMCP_API_KEY)
            except Exception as e:
                logger.warning(f"SDK client non inizializzabile: {e}")

    @property
    def name(self) -> str:
        return "metamcp"

    def get_tools(self) -> List[Dict[str, Any]]:
        return get_tool_catalog()

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if self._sdk_client is not None:
            try:
                return self._sdk_client.call_tool(tool_name, args)
            except Exception as e:
                logger.warning(f"SDK call fallito per '{tool_name}', fallback legacy: {e}")
        return self._client.call_tool(tool_name, args)
