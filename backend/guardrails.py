"""Guardrail di sicurezza per tool ad alto rischio (Fase 0.3).

Classifica i tool in base al rischio e blocca/limita le operazioni distruttive
sull'host Proxmox (exec_host_command, exec_lxc_command, snapshot delete, ecc.).
"""
import re
import logging
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
    "web_search",
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


def classify_tool(tool_name: str) -> str:
    """Ritorna 'safe', 'write' o 'risky' per un dato tool."""
    if tool_name in SAFE_TOOLS:
        return "safe"
    lowered = (tool_name or "").lower()
    for pat in RISKY_TOOL_PATTERNS:
        if re.search(pat, lowered):
            return "risky"
    return "write"


def check_shell_command(command: str) -> Tuple[bool, Optional[str]]:
    """Verifica se un comando shell contiene pattern vietati.

    Ritorna (allowed, reason). I pattern pericolosi sono sempre bloccati.
    """
    cmd = command or ""
    for pat, desc in DANGEROUS_SHELL_PATTERNS:
        if re.search(pat, cmd):
            return False, f"Comando bloccato dal guardrail: {desc}"
    return True, None


def enforce_guardrails(tool_name: str, args: Dict[str, Any]) -> Optional[str]:
    """Applica i guardrail prima dell'esecuzione di un tool.

    Ritorna None se il tool è autorizzato, altrimenti una stringa con il motivo del blocco.
    """
    risk = classify_tool(tool_name)

    # Per i tool exec_*, ispeziona il comando shell negli argomenti
    if risk == "risky" and ("command" in args or "cmd" in args):
        command = args.get("command") or args.get("cmd") or ""
        allowed, reason = check_shell_command(str(command))
        if not allowed:
            logger.warning(f"Guardrail: tool '{tool_name}' bloccato -> {reason}")
            return reason

    # Operazioni distruttive esplicite richiedono conferma esplicita nell'argomento
    if risk == "risky":
        confirm = args.get("confirm")
        if confirm is not True:
            return (
                f"Tool '{tool_name}' è classificato come rischioso (operazione potenzialmente distruttiva). "
                f"Imposta 'confirm': true negli argomenti per confermare l'esecuzione."
            )

    return None
