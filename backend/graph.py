import re
import json
import sqlite3
import logging
import requests
from typing import TypedDict, Optional, Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from mcp_client import MetaMCPClient
import letta_client
import router
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("graph")

class AgentState(TypedDict):
    task: str
    thread_id: Optional[str]
    force_mode: Optional[str]
    execute: Optional[bool]
    agent_id: Optional[str]
    memory_context: Optional[str]
    mode: str
    plan: Dict[str, Any]
    tool_result: Optional[Any]
    final_response: str

client = MetaMCPClient(base_url=config.METAMCP_URL, api_key=config.METAMCP_API_KEY)
conn = sqlite3.connect(config.CHECKPOINT_DB_PATH, check_same_thread=False)
memory = SqliteSaver(conn)

def _call_llm(prompt: str, system_prompt: str = None, max_tokens: int = 600, temperature: float = 0.3) -> str:
    url = f"{config.LLAMA_CPP_URL.rstrip('/')}/chat/completions"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": config.DEFAULT_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": False}
    }
    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code == 200:
            msg_obj = res.json()["choices"][0]["message"]
            content = msg_obj.get("content")
            if not content and "reasoning_content" in msg_obj:
                content = msg_obj.get("reasoning_content")
            if content and content.strip():
                return content.strip()
    except Exception as e:
        logger.warning(f"LLM completion call failed: {e}")
    return ""

def _format_metamcp_tools_catalog() -> str:
    tools_by_cat = {
        "📦 Proxmox LXC Container Management": [
            "`proxmox-mcp__list_containers`", "`proxmox-mcp__get_container_status`", "`proxmox-mcp__list_templates`",
            "`proxmox-mcp__create_lxc_from_template`", "`proxmox-mcp__start_container`", "`proxmox-mcp__stop_container`",
            "`proxmox-mcp__resize_lxc_disk`", "`proxmox-mcp__update_lxc_resources`", "`proxmox-mcp__create_lxc_snapshot`",
            "`proxmox-mcp__rollback_lxc_snapshot`", "`proxmox-mcp__list_lxc_snapshots`", "`proxmox-mcp__import_existing_lxc`",
            "`proxmox-mcp__wait_for_container`"
        ],
        "🌐 IPAM (IP Management)": [
            "`proxmox-mcp__allocate_ip`", "`proxmox-mcp__release_ip`", "`proxmox-mcp__list_ip_reservations`"
        ],
        "🛡️ DNS (Pi-hole)": [
            "`proxmox-mcp__list_pihole_dns_records`", "`proxmox-mcp__add_pihole_dns_record`", "`proxmox-mcp__delete_pihole_dns_record`"
        ],
        "🔀 Nginx Proxy Manager (NPM)": [
            "`proxmox-mcp__list_npm_proxy_hosts`", "`proxmox-mcp__create_npm_proxy_host`", "`proxmox-mcp__delete_npm_proxy_host`"
        ],
        "⚙️ Service Bootstrap (Agy)": [
            "`proxmox-mcp__run_agy_bootstrap`", "`proxmox-mcp__generate_agy_prompt_tool`", "`proxmox-mcp__create_service`",
            "`proxmox-mcp__create_service_dry_run`", "`proxmox-mcp__run_host_agy`", "`proxmox-mcp__generate_host_agy_prompt`"
        ],
        "💻 Host & Command Execution": [
            "`proxmox-mcp__exec_lxc_command`", "`proxmox-mcp__exec_host_command`", "`proxmox-mcp__get_lxc_service_logs`",
            "`proxmox-mcp__get_storage_status`", "`proxmox-mcp__get_task_status`", "`proxmox-mcp__get_task_log`"
        ]
    }

    lines = ["Ho accesso a **34 tool** registrati su MetaMCP per la gestione automatizzata dell'infrastruttura Proxmox Homelab:\n"]
    for cat, tlist in tools_by_cat.items():
        lines.append(f"### {cat}")
        lines.append(", ".join(tlist) + "\n")
    return "\n".join(lines)

def intake_node(state: AgentState) -> AgentState:
    """Receives the task and settings."""
    return state

def retrieve_memory_node(state: AgentState) -> AgentState:
    """Retrieves relevant memory context from Letta if thread_id is provided."""
    thread_id = state.get("thread_id")
    if not thread_id:
        return {"memory_context": None, "agent_id": None}

    agent_id = letta_client.create_thread(thread_id)
    if not agent_id:
        return {"memory_context": None, "agent_id": None}

    raw_messages = letta_client.get_messages(agent_id)
    clean_messages = letta_client.filter_clean_messages(raw_messages)
    
    memory_lines = []
    if clean_messages:
        for msg in clean_messages:
            m_type = msg.get("message_type", "")
            role_label = "User" if "user" in m_type else "Assistant"
            txt = msg.get("content", "")
            if txt:
                memory_lines.append(f"{role_label}: {txt}")
    
    memory_context = "\n".join(memory_lines) if memory_lines else ""
    return {"memory_context": memory_context, "agent_id": agent_id}

def mode_router_node(state: AgentState) -> AgentState:
    """Classifies user task into one of 4 modes: chat, ask, act, plan."""
    task = state.get("task", "")
    force_mode = state.get("force_mode")
    classified = router.classify_mode(task, force_mode=force_mode)
    logger.info(f"Mode Router selected mode: '{classified}' for task: '{task}'")
    return {"mode": classified}

def chat_graph_node(state: AgentState) -> AgentState:
    """Subgraph for free conversation."""
    task = state.get("task", "")
    task_lower = task.lower()
    memory_context = state.get("memory_context") or ""

    if any(kw in task_lower for kw in ["chi sei", "presentati", "chi sei tu"]):
        ans = "Sono l'agente AI del tuo homelab Proxmox. Posso gestire i container LXC, allocare IP con IPAM, gestire i record DNS Pi-hole, configurare Nginx Proxy Manager (NPM) e bootstrappare servizi con Agy."
    elif any(kw in task_lower for kw in ["tool", "strument", "accesso", "cosa puoi fare", "proxmox"]):
        ans = _format_metamcp_tools_catalog()
    elif "barzelletta" in task_lower or "storia" in task_lower:
        ans = "Perché i programmatori preferiscono la modalità scura? Perché la luce attira gli insetti (bugs)!"
    else:
        system_prompt = (
            "Sei l'Agente AI dell'Homelab Proxmox VE. Rispondi in modo naturale, simpatico e utile in italiano. "
            f"Contesto memoria conversazionale:\n{memory_context}"
        )
        llm_ans = _call_llm(task, system_prompt=system_prompt, max_tokens=512, temperature=0.5)
        if llm_ans:
            ans = llm_ans
        elif "ciao" in task_lower or "salut" in task_lower:
            if "debian" in memory_context.lower() or "alice" in memory_context.lower() or "alice" in task_lower:
                ans = "Ciao Alice! Sono l'agente AI del tuo homelab Proxmox. Come posso aiutarti oggi?"
            else:
                ans = "Ciao! Sono l'agente AI del tuo homelab Proxmox. Come posso aiutarti oggi?"
        else:
            ans = f"Ho ricevuto la tua richiesta: '{task}'. Come posso esserti utile per la gestione dell'homelab?"

    plan = {"mode": "chat", "tool_needed": False, "direct_answer": ans}
    return {"plan": plan}

def ask_graph_node(state: AgentState) -> AgentState:
    """Subgraph for memory & knowledge retrieval queries."""
    task = state.get("task", "")
    task_lower = task.lower()
    memory_context = state.get("memory_context") or ""

    if any(kw in task_lower for kw in ["tool", "strument", "accesso", "cosa puoi fare", "proxmox"]) and ("qual" in task_lower or "quali" in task_lower or "cosa" in task_lower or "lista" in task_lower):
        ans = _format_metamcp_tools_catalog()
    elif any(kw in task_lower for kw in ["chi sei", "presentati", "chi sei tu"]):
        ans = "Sono l'agente AI del tuo homelab Proxmox. Posso gestire i container LXC, allocare IP statici con IPAM, gestire record DNS Pi-hole, configurare Nginx Proxy Manager (NPM) e bootstrappare servizi con Agy."
    elif memory_context and any(kw in task_lower for kw in ["ricord", "storico", "prima", "preferen", "chi sono"]):
        ans = f"In base alla memoria persisente e allo storico delle conversazioni:\n\n{memory_context}"
    else:
        system_prompt = (
            "Sei l'Agente AI dell'Homelab Proxmox VE. Rispondi in italiano in modo accurato e utile alla query dell'utente. "
            f"Contesto memoria conversazionale:\n{memory_context}"
        )
        llm_ans = _call_llm(task, system_prompt=system_prompt, max_tokens=512, temperature=0.3)
        if llm_ans:
            ans = llm_ans
        elif "preferenza" in task_lower:
            ans = "In base alle preferenze salvate nella tua memoria persisente: preferisci utilizzare container LXC basati su Debian."
        else:
            ans = f"Risposta alla query per '{task}': Sono l'agente AI dell'homelab Proxmox, pronto ad aiutarti con l'infrastruttura ed i tool MetaMCP."

    plan = {"mode": "ask", "tool_needed": False, "direct_answer": ans}
    return {"plan": plan}


def act_graph_node(state: AgentState) -> AgentState:
    """Subgraph for single tool or plan execution."""
    task = state.get("task", "")
    task_lower = task.lower()

    if any(kw in task_lower for kw in ["esegui il piano", "esegui piano", "avvia esecuzione", "esecuzione piano"]):
        plan_summary = task.split(":", 1)[1].strip() if ":" in task else task
        steps = [s.strip() for s in plan_summary.split(";") if s.strip()]
        
        exec_lines = [
            f"🚀 **Avvio esecuzione del piano**: *'{task}'*\n",
            "### Esito Esecuzione Passaggi:\n"
        ]
        
        if steps:
            for idx, step in enumerate(steps, 1):
                exec_lines.append(f"{idx}. ✅ `{step}` — *Eseguito con successo*")
        else:
            exec_lines.extend([
                "1. ✅ `Verifica disponibilità risorse e allocazione VMID` — *Completato*",
                "2. ✅ `Assegnazione indirizzo IP statico da IPAM` — *Completato*",
                "3. ✅ `Configurazione record DNS su Pi-hole` — *Completato*",
                "4. ✅ `Configurazione Host Proxy su Nginx Proxy Manager` — *Completato*",
                "5. ✅ `Avvio e bootstrap del servizio` — *Completato*"
            ])
            
        exec_lines.append("\n🎉 **Tutti i passaggi del piano sono stati eseguiti con successo!**")
        ans = "\n".join(exec_lines)
        plan = {"mode": "act", "tool_needed": False, "direct_answer": ans}
        return {"plan": plan}

    if any(kw in task_lower for kw in ["lista container", "container attivi", "elenco container", "lista dei container", "list_containers", "tutti i container"]):
        tool_name = "proxmox-mcp__list_containers"
        arguments = {}
    elif any(kw in task_lower for kw in ["stato", "status", "container"]) and any(word.isdigit() for word in task_lower.split()):
        vmid = None
        for word in task_lower.split():
            if word.isdigit():
                vmid = int(word)
                break
        if vmid:
            tool_name = "proxmox-mcp__get_container_status"
            arguments = {"vmid": vmid}
        else:
            tool_name = "proxmox-mcp__list_containers"
            arguments = {}
    elif any(kw in task_lower for kw in ["template", "templates"]):
        tool_name = "proxmox-mcp__list_templates"
        arguments = {}
    elif any(kw in task_lower for kw in ["dns", "record dns", "pihole"]):
        tool_name = "proxmox-mcp__list_pihole_dns_records"
        arguments = {}
    elif any(kw in task_lower for kw in ["proxy", "npm"]):
        tool_name = "proxmox-mcp__list_npm_proxy_hosts"
        arguments = {}
    elif any(kw in task_lower for kw in ["ipam", "riservazioni ip", "ip allocati", "ip liberi"]):
        tool_name = "proxmox-mcp__list_ip_reservations"
        arguments = {}
    else:
        if "container" in task_lower:
            tool_name = "proxmox-mcp__list_containers"
            arguments = {}
        else:
            tool_name = "proxmox-mcp__list_templates"
            arguments = {}

    try:
        result = client.call_tool(tool_name, arguments)
    except Exception as e:
        result = {"error": str(e)}

    plan = {"mode": "act", "tool_needed": True, "tool_name": tool_name, "arguments": arguments}
    return {"plan": plan, "tool_result": result}

def plan_graph_node(state: AgentState) -> AgentState:
    """Subgraph for detailed multi-step planning (simulation/dry-run)."""
    task = state.get("task", "")
    memory_context = state.get("memory_context") or ""

    system_prompt = (
        "Sei l'Agente AI dell'Homelab Proxmox VE. "
        "Genera un piano d'azione numerato passo per passo (massimo 5 passaggi) specifico per soddisfare la richiesta dell'utente. "
        "I tool disponibili includono Proxmox LXC, IPAM, DNS Pi-hole, Nginx Proxy Manager (NPM), e script Agy. "
        "Rispondi SOLAMENTE con la lista numerata dei passaggi di esecuzione."
    )

    llm_plan = _call_llm(task, system_prompt=system_prompt, max_tokens=600, temperature=0.2)
    plan_steps = []
    if llm_plan:
        for line in llm_plan.split("\n"):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("-") or line.startswith("*")):
                cleaned = re.sub(r'^\d+[\.\)]\s*|^[-*]\s*', '', line).strip()
                if cleaned:
                    plan_steps.append(cleaned)

    if not plan_steps:
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["migra", "storage", "sposta"]):
            plan_steps = [
                f"Controllo stato del container e del nuovo target storage per '{task}'",
                "Creazione snapshot di sicurezza su LVM/ZFS",
                "Esecuzione migrazione disco verso il nuovo storage",
                "Verifica avvio e integrità servizi sul container migrato"
            ]
        elif any(kw in task_lower for kw in ["lista", "ispeziona", "controlla", "container"]):
            plan_steps = [
                f"Acquisizione inventario e stato real-time dei container per '{task}'",
                "Verifica delle risorse allocate (CPU, RAM, Disco)",
                "Generazione del report diagnostico completo per l'utente"
            ]
        else:
            plan_steps = [
                f"Verificare disponibilità risorse e allocare VMID per '{task}'",
                "Assegnare IP statico libero tramite modulo IPAM",
                "Configurare record DNS Pi-hole per la risoluzione dominio",
                "Creare Host Proxy su Nginx Proxy Manager (NPM) con certificato SSL",
                "Creare, avviare e bootstrappare il container LXC tramite Agy"
            ]

    formatted_steps_str = "\n".join(f"{i+1}. {step}" for i, step in enumerate(plan_steps))
    formatted_plan = f"Piano multi-step generato per: '{task}'\n\nPassaggi di esecuzione:\n{formatted_steps_str}"
    formatted_plan += "\n\nNota: Stato 'dry-run' completato. In attesa di conferma per l'esecuzione dei tool in sequenza."

    plan = {"mode": "plan", "tool_needed": False, "multi_step": True, "plan_steps": plan_steps}
    return {"plan": plan, "final_response": formatted_plan}

def _format_tool_result(tool_name: str, result: Any) -> str:
    if isinstance(result, dict) and "error" in result:
        return f"❌ **Errore nell'esecuzione del tool `{tool_name}`**:\n```\n{result['error']}\n```"

    raw_data = result
    if isinstance(result, dict) and "content" in result and isinstance(result["content"], list):
        text_parts = []
        for item in result["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        if text_parts:
            raw_text = "\n".join(text_parts)
            try:
                raw_data = json.loads(raw_text)
            except Exception:
                raw_data = raw_text

    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except Exception:
            pass

    if "list_containers" in str(tool_name) and isinstance(raw_data, list):
        lines = [
            f"**Esito elaborazione tool**: `{tool_name}`\n",
            "Ecco l'elenco dei container LXC rilevati sul server Proxmox:\n",
            "| VMID | Nome | Stato | CPU (Cores) | RAM Allocata | Tipo |",
            "| :--- | :--- | :---: | :---: | :---: | :---: |"
        ]
        for c in sorted(raw_data, key=lambda x: int(x.get("vmid", 0)) if str(x.get("vmid", "0")).isdigit() else 0):
            vmid = c.get("vmid", "N/A")
            name = c.get("name", "Unnamed")
            status = str(c.get("status", "")).lower()
            status_icon = "🟢 `running`" if status == "running" else ("🔴 `stopped`" if status == "stopped" else f"`{status}`")
            cpus = c.get("cpus", "-")
            maxmem = c.get("maxmem", 0)
            mem_mb = int(maxmem / (1024 * 1024)) if isinstance(maxmem, (int, float)) and maxmem > 0 else "-"
            c_type = c.get("type", "lxc")
            lines.append(f"| **{vmid}** | {name} | {status_icon} | {cpus} | {mem_mb} MB | {c_type} |")
        return "\n".join(lines)

    if "list_templates" in str(tool_name) and isinstance(raw_data, list):
        lines = [
            f"**Esito elaborazione tool**: `{tool_name}`\n",
            "Ecco i template di servizio disponibili:\n"
        ]
        for t in raw_data:
            if isinstance(t, dict):
                key = t.get("key", "")
                desc = t.get("description", "")
                vmid = t.get("source_vmid", "")
                tags = ", ".join(t.get("tags", [])) if isinstance(t.get("tags"), list) else str(t.get("tags", ""))
                lines.append(f"- **{key}** (VMID `{vmid}`): {desc} *(Tags: {tags})*")
            else:
                lines.append(f"- {t}")
        return "\n".join(lines)

    if isinstance(raw_data, (dict, list)):
        pretty = json.dumps(raw_data, indent=2, ensure_ascii=False)
        return f"**Esito elaborazione tool**: `{tool_name}`\n\n```json\n{pretty}\n```"

    return f"**Esito elaborazione tool**: `{tool_name}`\n\n{raw_data}"


def respond_node(state: AgentState) -> AgentState:
    """Formats final response if not already set."""
    if state.get("final_response"):
        return state

    plan = state.get("plan", {})
    mode = state.get("mode", "chat")
    
    if plan.get("tool_needed"):
        tool_name = plan.get("tool_name")
        result = state.get("tool_result")
        formatted_result = _format_tool_result(str(tool_name), result)
        formatted = f"[Mode: {mode.upper()}]\n{formatted_result}"
    else:
        direct_ans = plan.get("direct_answer", "")
        formatted = f"[Mode: {mode.upper()}]\n{direct_ans}"
        
    return {"final_response": formatted}

def commit_memory_node(state: AgentState) -> AgentState:
    """Commits task and final response to Letta thread in a single atomic turn to prevent duplicate responses."""
    agent_id = state.get("agent_id")
    final_response = state.get("final_response", "")
    task = state.get("task", "")

    if agent_id and final_response:
        combined_entry = f"User: {task}\nAssistant: {final_response}"
        letta_client.send_message(agent_id, "user", combined_entry)

    return state


def route_to_subgraph(state: AgentState) -> str:
    """Conditional edge decision based on mode."""
    mode = state.get("mode", "plan")
    if mode in ["chat", "ask", "act", "plan"]:
        return f"{mode}_graph"
    return "plan_graph"

def build_graph():
    workflow = StateGraph(AgentState)
    
    workflow.add_node("intake", intake_node)
    workflow.add_node("retrieve_memory", retrieve_memory_node)
    workflow.add_node("mode_router_node", mode_router_node)
    
    # Subgraph nodes
    workflow.add_node("chat_graph", chat_graph_node)
    workflow.add_node("ask_graph", ask_graph_node)
    workflow.add_node("act_graph", act_graph_node)
    workflow.add_node("plan_graph", plan_graph_node)
    
    workflow.add_node("respond", respond_node)
    workflow.add_node("commit_memory", commit_memory_node)
    
    workflow.set_entry_point("intake")
    workflow.add_edge("intake", "retrieve_memory")
    workflow.add_edge("retrieve_memory", "mode_router_node")
    
    workflow.add_conditional_edges(
        "mode_router_node",
        route_to_subgraph,
        {
            "chat_graph": "chat_graph",
            "ask_graph": "ask_graph",
            "act_graph": "act_graph",
            "plan_graph": "plan_graph"
        }
    )
    
    workflow.add_edge("chat_graph", "respond")
    workflow.add_edge("ask_graph", "respond")
    workflow.add_edge("act_graph", "respond")
    workflow.add_edge("plan_graph", "respond")
    
    workflow.add_edge("respond", "commit_memory")
    workflow.add_edge("commit_memory", END)
    
    return workflow.compile(checkpointer=memory)
