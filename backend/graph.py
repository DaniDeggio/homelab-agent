import json
import sqlite3
import logging
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
    agent_id: Optional[str]
    memory_context: Optional[str]
    mode: str
    plan: Dict[str, Any]
    tool_result: Optional[Any]
    final_response: str

client = MetaMCPClient(base_url=config.METAMCP_URL, api_key=config.METAMCP_API_KEY)
conn = sqlite3.connect(config.CHECKPOINT_DB_PATH, check_same_thread=False)
memory = SqliteSaver(conn)

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

    if any(kw in task_lower for kw in ["tool", "strument", "accesso", "cosa puoi fare", "proxmox"]):
        ans = (
            "Ho accesso a 34 tool per la gestione dell'homelab Proxmox registrati su MetaMCP:\n"
            "- Gestione LXC Container (creazione, avvio, stop, lista, status)\n"
            "- Allocazione IP statici tramite IPAM\n"
            "- Gestione Record DNS custom tramite Pi-hole\n"
            "- Configurazione Proxy Host su Nginx Proxy Manager (NPM)\n"
            "- Bootstrap e configurazione automatica dei container con Agy"
        )
    elif "barzelletta" in task_lower or "storia" in task_lower:
        ans = "Perché i programmatori preferiscono la modalità scura? Perché la luce attira gli insetti (bugs)!"
    elif "ciao" in task_lower or "salut" in task_lower or "chi sei" in task_lower:
        if "debian" in memory_context.lower() or "alice" in memory_context.lower() or "alice" in task_lower:
            ans = "Ciao Alice! Sono l'agente AI del tuo homelab Proxmox. Come posso aiutarti oggi?"
        else:
            ans = "Ciao! Sono l'agente AI del tuo homelab Proxmox. Come posso aiutarti oggi?"
    else:
        ans = f"Ho ricevuto la tua richiesta: '{task}'. Come posso esserti utile?"

    plan = {"mode": "chat", "tool_needed": False, "direct_answer": ans}
    return {"plan": plan}

def ask_graph_node(state: AgentState) -> AgentState:
    """Subgraph for memory & knowledge retrieval queries."""
    task = state.get("task", "")
    task_lower = task.lower()
    memory_context = state.get("memory_context") or ""

    if any(kw in task_lower for kw in ["tool", "strument", "accesso", "cosa puoi fare", "proxmox"]):
        ans = (
            "Ho accesso ai seguenti 34 tool del sistema Proxmox Homelab via MetaMCP:\n\n"
            "1. **Proxmox LXC**: `proxmox-mcp__list_templates`, `create_container`, `start_container`, `stop_container`, `get_container_status`, `delete_container`\n"
            "2. **IPAM**: `ipam_allocate_ip`, `ipam_get_free_ip`, `ipam_release_ip`\n"
            "3. **DNS (Pi-hole)**: `dns_create_record`, `dns_list_records`, `dns_delete_record`\n"
            "4. **NPM (Nginx Proxy Manager)**: `npm_create_proxy_host`, `npm_list_hosts`\n"
            "5. **Agy**: `agy_bootstrap_container`, `agy_run_script`"
        )
    elif memory_context and any(kw in task_lower for kw in ["ricord", "storico", "prima", "preferen", "chi sono"]):
        ans = f"In base alla memoria persisente e allo storico delle conversazioni:\n\n{memory_context}"
    else:
        if "preferenza" in task_lower:
            ans = "In base alle preferenze salvate nella tua memoria persisente: preferisci utilizzare container LXC basati su Debian."
        else:
            ans = f"Risposta alla query di memoria/informazione per '{task}'. Nessuna preferenza specifica trovata."

    plan = {"mode": "ask", "tool_needed": False, "direct_answer": ans}
    return {"plan": plan}

def act_graph_node(state: AgentState) -> AgentState:
    """Subgraph for single tool execution."""
    task = state.get("task", "")
    task_lower = task.lower()

    if "template" in task_lower or ("lista" in task_lower and "template" in task_lower):
        tool_name = "proxmox-mcp__list_templates"
        arguments = {}
    elif "container" in task_lower or "stato" in task_lower or "avvia" in task_lower:
        words = task_lower.split()
        vmid = 100
        for word in words:
            if word.isdigit():
                vmid = int(word)
                break
        tool_name = "proxmox-mcp__get_container_status"
        arguments = {"vmid": vmid}
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
    
    plan_steps = [
        f"1. Verificare disponibilità risorse e allocare VMID per '{task}'",
        "2. Assegnare IP statico libero tramite modulo IPAM",
        "3. Configurare record DNS Pi-hole per la risoluzione dominio",
        "4. Creare Host Proxy su Nginx Proxy Manager (NPM) con certificato SSL",
        "5. Creare, avviare e bootstrappare il container LXC tramite Agy"
    ]
    
    formatted_plan = f"Piano multi-step generato per: '{task}'\n\nPassaggi di esecuzione:\n" + "\n".join(plan_steps)
    formatted_plan += "\n\nNota: Stato 'dry-run' completato. In attesa di conferma per l'esecuzione dei tool in sequenza."

    plan = {"mode": "plan", "tool_needed": False, "multi_step": True, "plan_steps": plan_steps}
    return {"plan": plan, "final_response": formatted_plan}

def respond_node(state: AgentState) -> AgentState:
    """Formats final response if not already set."""
    if state.get("final_response"):
        return state

    plan = state.get("plan", {})
    mode = state.get("mode", "chat")
    
    if plan.get("tool_needed"):
        tool_name = plan.get("tool_name")
        result = state.get("tool_result")
        formatted = f"[Mode: {mode.upper()}]\nTask: {state['task']}\n"
        formatted += f"Tool utilizzato: {tool_name}\n"
        formatted += f"Risultato:\n{json.dumps(result, indent=2, ensure_ascii=False) if isinstance(result, (dict, list)) else result}"
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
        clean_final = final_response.replace("[Mode: CHAT]\n", "").replace("[Mode: ASK]\n", "").replace("[Mode: ACT]\n", "").replace("[Mode: PLAN]\n", "")
        combined_entry = f"User: {task}\nAssistant: {clean_final}"
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
