import sys
import os
from typing import List, Dict, Any

# Assicura che la directory backend sia nell'import path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from registry.base import BaseToolRegistry
from tool_catalog import get_tool_catalog
from mcp_client import MetaMCPClient
import config

class MetaMCPRegistry(BaseToolRegistry):
    def __init__(self):
        self._client = MetaMCPClient(config.METAMCP_URL, api_key=config.METAMCP_API_KEY)

    @property
    def name(self) -> str:
        return "metamcp"

    def get_tools(self) -> List[Dict[str, Any]]:
        return get_tool_catalog()

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        return self._client.call_tool(tool_name, args)
