"""Guardrail di sicurezza per tool ad alto rischio (Fasi 0.3 e 3.1-3.2).

Classifica i tool in base al rischio, blocca/limita le operazioni distruttive
sull'host Proxmox e gestisce il workflow di approvazione utente.
"""
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("guardrails")

# --- Classificazione rischio tool ---

RISKY_TOOL_PATTERNS = [
    r"delete", r"remove", r"rollback", r"stop", r"shutdown", r"reboot",
    r"destroy", r"exec_", r"host_command", r"lxc_command", r"provision",
]

# Tool considerati read-only / sicuri
SAFE_TOOLS = {
    "list_containers", "get_container_status", "get_lxc_service_logs",
    "list_pihole_dns_records", "list_npm_proxy_hosts", "list_lxc_snapshots",
    "list_ip_reservations", "list_templates", "get_storage_status",
    "get_task_status", "get_task_log", "web_search",
    "recall_memory", "knowledge_search",
}

# --- Fase 3.1: metadata di categoria per tool ---
TOOL_CATEGORIES = {
    "list_containers": "proxmox.read", "get_container_status": "proxmox.read",
    "list_templates": "proxmox.read", "list_lxc_snapshots": "proxmox.read",
    "create_lxc_from_template": "proxmox.write", "start_container": "proxmox.write",
    "stop_container": "proxmox.destructive", "rollback_lxc_snapshot": "proxmox.destructive",
    "resize_lxc_disk": "proxmox.write", "update_lxc_resources": "proxmox.write",
    "allocate_ip": "ipam.write", "release_ip": "ipam.destructive",
    "add_pihole_dns_record": "dns.write", "delete_pihole_dns_record": "dns.destructive",
    "create_npm_proxy_host": "proxy.write", "delete_npm_proxy_host": "proxy.destructive",
    "exec_lxc_command": "host.exec", "exec_host_command": "host.exec.dangerous",
    "run_agy_bootstrap": "provisioning", "create_service": "provisioning",
    "python_interpreter": "code.sandboxed", "web_search": "web.read",
    "recall_memory": "memory.read", "knowledge_search": "kb.read",
}

# Pattern di comandi shell vietati dentro exec_*_command
DANGEROUS_SHELL_PATTERNS = [
    (r"\brm\s+-rf?\s+/(?!tmp|home|opt/homelab)", "rm ricorsivo su path di sistema"),
    (r"\bmkfs(\.\w+)?\b", "formattazione filesystem"),
    (r"\bdd\s+.*\bof=/dev/", "dd verso device"),
    (r":\(\)\s*\{.*\};\s*:", "fork bomb"),
    (r"\b(shutdown|reboot|poweroff|halt)\b", "spegnimento/riavvio sistema"),
    (r">\s*/dev/sd[a-z]", "scrittura diretta su disco"),
    (r"\bchmod\s+-R?\s*777\s+/", "chmod 777 su root"),
    (r"\biptables\s+-F\b", "flush regole firewall"),
]


def check_shell_command(command: str) -> Tuple[bool, Optional[str]]:
    """Verifica se un comando shell contiene pattern vietati.

    Ritorna (allowed, reason). I pattern pericolosi sono sempre bloccati.
    """
    cmd = command or ""
    for pat, desc in DANGEROUS_SHELL_PATTERNS:
        if re.search(pat, cmd):
            return False, f"Comando bloccato dal guardrail: {desc}"
    return True, None


def classify_tool(tool_name: str) -> str:
    """Ritorna 'safe', 'write' o 'risky' per un dato tool."""
    if tool_name in SAFE_TOOLS:
        return "safe"
    lowered = (tool_name or "").lower()
    for pat in RISKY_TOOL_PATTERNS:
        if re.search(pat, lowered):
            return "risky"
    return "write"


# --- Fase 3.1: metadata arricchiti per il tool registry ---

def get_tool_metadata(tool_name: str) -> Dict[str, Any]:
    """Restituisce i metadata completi di un tool: rischio, categoria, read-only, reversibilità."""
    from tool_catalog import get_rollback_info
    risk = classify_tool(tool_name)
    category = TOOL_CATEGORIES.get(tool_name) or TOOL_CATEGORIES.get(
        (tool_name or "").replace("proxmox-mcp__", ""), "other"
    )
    return {
        "risk": risk,
        "category": category,
        "read_only": risk == "safe",
        "requires_approval": risk == "risky",
        "reversible": get_rollback_info(tool_name).get("reversible", False),
    }


def enrich_catalog_with_metadata(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggiunge i metadata di rischio a ogni entry del catalogo tool."""
    for t in tools:
        t["metadata"] = get_tool_metadata(t.get("name", ""))
    return tools


# --- Fase 3.2: approval workflow per tool rischiosi ---

class ApprovalRequest:
    __slots__ = ("request_id", "tool_name", "arguments", "thread_id", "mode", "created_at", "status", "resolved_by")

    def __init__(self, request_id: str, tool_name: str, arguments: Dict[str, Any],
                 thread_id: Optional[str], mode: Optional[str]):
        self.request_id = request_id
        self.tool_name = tool_name
        self.arguments = arguments
        self.thread_id = thread_id
        self.mode = mode
        self.created_at = time.time()
        self.status = "pending"  # pending | approved | denied | expired
        self.resolved_by: Optional[str] = None


_APPROVALS: Dict[str, ApprovalRequest] = {}
_approval_lock = threading.Lock()
APPROVAL_TTL_SECONDS = 300  # le richieste scadono dopo 5 minuti

def _next_request_id() -> str:
    import uuid
    return f"apr_{uuid.uuid4().hex[:12]}"


def create_approval_request(tool_name: str, arguments: Dict[str, Any],
                            thread_id: Optional[str] = None, mode: Optional[str] = None) -> ApprovalRequest:
    req = ApprovalRequest(_next_request_id(), tool_name, arguments, thread_id, mode)
    with _approval_lock:
        # Pulizia richieste scadute
        now = time.time()
        expired = [k for k, v in _APPROVALS.items()
                   if v.status == "pending" and now - v.created_at > APPROVAL_TTL_SECONDS]
        for k in expired:
            _APPROVALS[k].status = "expired"
        _APPROVALS[req.request_id] = req
    logger.info(f"Approval request creata: {req.request_id} per tool '{tool_name}'")
    return req


def resolve_approval(request_id: str, approved: bool, resolved_by: str = "user") -> Optional[ApprovalRequest]:
    """Approva o nega una richiesta pendente."""
    with _approval_lock:
        req = _APPROVALS.get(request_id)
        if not req or req.status != "pending":
            return None
        if time.time() - req.created_at > APPROVAL_TTL_SECONDS:
            req.status = "expired"
            return req
        req.status = "approved" if approved else "denied"
        req.resolved_by = resolved_by
    logger.info(f"Approval {request_id}: {'APPROVATA' if approved else 'NEGATA'} da {resolved_by}")
    return req


def get_pending_approvals(thread_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Elenca le richieste di approvazione pendenti (opzionalmente filtrate per thread)."""
    with _approval_lock:
        now = time.time()
        result = []
        for req in _APPROVALS.values():
            if req.status != "pending":
                continue
            if now - req.created_at > APPROVAL_TTL_SECONDS:
                req.status = "expired"
                continue
            if thread_id and req.thread_id != thread_id:
                continue
            result.append({
                "request_id": req.request_id,
                "tool_name": req.tool_name,
                "arguments": req.arguments,
                "thread_id": req.thread_id,
                "mode": req.mode,
                "age_seconds": int(now - req.created_at),
            })
        return result


def enforce_guardrails(tool_name: str, args: Dict[str, Any], *,
                       thread_id: Optional[str] = None, mode: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Applica i guardrail prima dell'esecuzione di un tool (Fase 3.2).

    Ritorna:
      - None se il tool è autorizzato all'esecuzione immediata
      - {"approval_required": True, "request_id": ..., "message": ...} se serve approvazione utente
      - {"blocked": True, "reason": ...} se il tool è bloccato dai guardrail
    """
    risk = classify_tool(tool_name)

    # Per i tool exec_*, ispeziona il comando shell negli argomenti
    if risk == "risky" and ("command" in args or "cmd" in args):
        command = args.get("command") or args.get("cmd") or ""
        allowed, reason = check_shell_command(str(command))
        if not allowed:
            logger.warning(f"Guardrail: tool '{tool_name}' bloccato -> {reason}")
            return {"blocked": True, "reason": reason}

    # Operazioni distruttive: creano una richiesta di approvazione (Fase 3.2)
    if risk == "risky":
        confirm = args.get("confirm")
        if confirm is not True:
            req = create_approval_request(tool_name, args, thread_id=thread_id, mode=mode)
            return {
                "approval_required": True,
                "request_id": req.request_id,
                "message": (
                    f"Il tool '{tool_name}' è classificato come rischioso (operazione potenzialmente distruttiva). "
                    f"Richiesta di approvazione '{req.request_id}' creata: in attesa di conferma utente."
                ),
            }

    return None
