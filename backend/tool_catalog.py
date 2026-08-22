import time
import logging
import requests
import config
from mcp_client import MetaMCPClient

logger = logging.getLogger("tool_catalog")

_catalog_cache = {"data": None, "timestamp": 0}
CACHE_TTL_SECONDS = 300  # 5 minuti

ROLLBACK_DECLARATIONS = {
    "proxmox-mcp__allocate_ip": {
        "rollback_tool": "proxmox-mcp__release_ip",
        "rollback_args_template": {"ip": "{{ip}}"},
        "reversible": True
    },
    "allocate_ip": {
        "rollback_tool": "proxmox-mcp__release_ip",
        "rollback_args_template": {"ip": "{{ip}}"},
        "reversible": True
    },
    "proxmox-mcp__create_lxc_from_template": {
        "rollback_tool": "proxmox-mcp__stop_container",
        "rollback_args_template": {"vmid": "{{vmid}}"},
        "reversible": True
    },
    "create_lxc_from_template": {
        "rollback_tool": "proxmox-mcp__stop_container",
        "rollback_args_template": {"vmid": "{{vmid}}"},
        "reversible": True
    },
    "proxmox-mcp__add_pihole_dns_record": {
        "rollback_tool": "proxmox-mcp__delete_pihole_dns_record",
        "rollback_args_template": {"domain": "{{domain}}", "target_ip": "{{target_ip}}"},
        "reversible": True
    },
    "add_pihole_dns_record": {
        "rollback_tool": "proxmox-mcp__delete_pihole_dns_record",
        "rollback_args_template": {"domain": "{{domain}}", "target_ip": "{{target_ip}}"},
        "reversible": True
    },
    "proxmox-mcp__create_npm_proxy_host": {
        "rollback_tool": "proxmox-mcp__delete_npm_proxy_host",
        "rollback_args_template": {"domain": "{{domain}}"},
        "reversible": True
    },
    "create_npm_proxy_host": {
        "rollback_tool": "proxmox-mcp__delete_npm_proxy_host",
        "rollback_args_template": {"domain": "{{domain}}"},
        "reversible": True
    },
    "proxmox-mcp__list_containers": {"reversible": False},
    "list_containers": {"reversible": False},
    "proxmox-mcp__exec_lxc_command": {"reversible": False},
    "exec_lxc_command": {"reversible": False},
}

def get_rollback_info(tool_name: str) -> dict:
    """Recupera info di rollback per un tool, se dichiarato."""
    if not tool_name:
        return {"reversible": False}
    if tool_name in ROLLBACK_DECLARATIONS:
        return ROLLBACK_DECLARATIONS[tool_name]
    clean_name = tool_name.replace("proxmox-mcp__", "")
    if clean_name in ROLLBACK_DECLARATIONS:
        return ROLLBACK_DECLARATIONS[clean_name]
    return {"reversible": False}

def get_tool_catalog(force_refresh: bool = False) -> list[dict]:
    """
    Recupera il catalogo tool da MetaMCP via list_tools (SSE/REST) o OpenAPI, con cache TTL 5m.
    Ogni entry: {"name": str, "description": str, "parameters": dict, "rollback_info": dict}
    """
    now = time.time()
    if not force_refresh and _catalog_cache["data"] and (now - _catalog_cache["timestamp"] < CACHE_TTL_SECONDS):
        return _catalog_cache["data"]

    tools = []
    # 1. Prova via MetaMCPClient list_tools (SSE/REST MCP protocol)
    try:
        mcp = MetaMCPClient(config.METAMCP_URL, api_key=config.METAMCP_API_KEY)
        raw_tools = mcp.list_tools()
        if raw_tools and isinstance(raw_tools, list):
            for t in raw_tools:
                if isinstance(t, dict):
                    name = t.get("name", "")
                    desc = t.get("description", "")
                    params = t.get("inputSchema") or t.get("parameters") or {"type": "object", "properties": {}}
                    tools.append({
                        "name": name,
                        "description": desc,
                        "parameters": params
                    })
    except Exception as e:
        logger.warning(f"Chiamata SSE/MCP list_tools fallita: {e}")

    # 2. Fallback OpenAPI se list_tools è vuoto
    if not tools:
        base_http = getattr(config, "METAMCP_URL_HTTP", "http://192.168.1.175:12008").rstrip('/')
        url = f"{base_http}/api/openapi.json"
        headers = {"Authorization": f"Bearer {config.METAMCP_API_KEY}"} if config.METAMCP_API_KEY else {}
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                openapi = res.json()
                tools = _parse_openapi_to_tools(openapi)
        except Exception as e:
            logger.warning(f"Impossibile recuperare OpenAPI da MetaMCP ({e})")

    if tools:
        for t in tools:
            t["rollback_info"] = get_rollback_info(t.get("name", ""))
        # Fase 3.1: metadata di rischio/categoria per ogni tool
        from guardrails import enrich_catalog_with_metadata
        tools = enrich_catalog_with_metadata(tools)
        _catalog_cache["data"] = tools
        _catalog_cache["timestamp"] = now
        logger.info(f"Catalogo tool aggiornato: {len(tools)} tool disponibili")
        return tools

    cached = _catalog_cache["data"] or []
    for t in cached:
        t["rollback_info"] = get_rollback_info(t.get("name", ""))
    return cached

def _parse_openapi_to_tools(openapi: dict) -> list[dict]:
    """Estrae {name, description, parameters} da uno schema OpenAPI."""
    tools = []
    paths = openapi.get("paths", {})
    for path, methods in paths.items():
        if isinstance(methods, dict):
            for method, spec in methods.items():
                if isinstance(spec, dict):
                    name = spec.get("operationId") or path.strip("/").replace("/", "_")
                    description = spec.get("summary") or spec.get("description") or ""
                    params_schema = spec.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
                    tools.append({
                        "name": name,
                        "description": description,
                        "parameters": params_schema
                    })
    return tools

def format_catalog_for_prompt(tools: list[dict]) -> str:
    """Formatta il catalogo in modo compatto per il prompt LLM."""
    lines = []
    for t in tools:
        params_dict = t.get("parameters", {})
        props = params_dict.get("properties", {}) if isinstance(params_dict, dict) else {}
        params_summary = ", ".join(props.keys()) if isinstance(props, dict) else ""
        lines.append(f"- `{t['name']}`: {t['description']} (args: {params_summary or 'nessuno'})")
    return "\n".join(lines)
