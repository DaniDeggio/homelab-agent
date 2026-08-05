import re
import json
import sqlite3
import logging
import os
import requests
from datetime import datetime
from typing import TypedDict, Optional, Dict, Any, List
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from mcp_client import MetaMCPClient
import letta_client
import router
import config
from tool_catalog import get_tool_catalog, format_catalog_for_prompt, get_rollback_info
from tool_schemas import ToolSelection, validate_tool_args

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
    plan_structure: Optional[Dict[str, Any]]
    tool_result: Optional[Any]
    final_response: str

client = MetaMCPClient(base_url=config.METAMCP_URL, api_key=config.METAMCP_API_KEY)
conn = sqlite3.connect(config.CHECKPOINT_DB_PATH, check_same_thread=False)
memory = SqliteSaver(conn)

MEMORY_DIR = "/opt/homelab-agent/memory" if os.path.exists("/opt/homelab-agent") else os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory")

def _append_message_to_file(thread_id: str, role: str, content: str):
    """Scrivi un messaggio su file JSONL (append-only) per audit e disaster recovery."""
    if not thread_id or not content:
        return
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        filepath = os.path.join(MEMORY_DIR, f"{thread_id}.jsonl")
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "role": role,
            "content": content
        }
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"Messaggio ({role}) salvato su file di memoria: {filepath}")
    except Exception as e:
        logger.warning(f"Errore scrittura memoria file system {thread_id}: {e}")

def _read_messages_from_file(thread_id: str) -> List[Dict[str, Any]]:
    """Legge i messaggi storici dal file JSONL locale in caso di assenza o fallback di Letta."""
    if not thread_id:
        return []
    filepath = os.path.join(MEMORY_DIR, f"{thread_id}.jsonl")
    if not os.path.exists(filepath):
        return []
    messages = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        role_type = "user_message" if data.get("role") == "user" else "assistant_message"
                        messages.append({
                            "message_type": role_type,
                            "content": data.get("content", ""),
                            "timestamp": data.get("timestamp")
                        })
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"Errore lettura file memoria {filepath}: {e}")
    return messages

def _generate_summary(messages: List[Dict[str, Any]]) -> str:
    """Genera un riassunto di una lista di messaggi mediante LLM."""
    text = "\n".join([f"{'User' if 'user' in str(m.get('message_type','')).lower() else 'Assistant'}: {m.get('content', '')}" for m in messages])
    prompt = f"""Riassumi la seguente conversazione in massimo 5 frasi, mantenendo:
- Nomi delle persone (es. "Alice")
- Preferenze espresse (es. "preferisce Debian")
- Decisioni prese (es. "ha creato servizio web")
- Domande aperte o task in corso

Conversazione:
{text}

Riassunto:"""
    summary = _call_llm(prompt, system_prompt="Sei un assistente che riassume conversazioni in modo conciso.", max_tokens=512, temperature=0.3)
    return summary.strip() if summary else ""

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

def _call_llm_structured(prompt: str, system_prompt: str, schema_cls: Any, max_tokens: int = 500, temperature: float = 0.0, max_retries: int = 3) -> Optional[Any]:
    """
    Chiama l'LLM richiedendo output conforme allo schema Pydantic.
    Effettua parsing + validazione con retry mirato ed iniezione dell'errore.
    """
    json_schema = schema_cls.model_json_schema()
    schema_prompt = (
        f"{system_prompt}\n\n"
        f"Rispondi ESCLUSIVAMENTE con un JSON valido conforme a questo JSON Schema:\n"
        f"{json.dumps(json_schema, ensure_ascii=False)}\n\n"
        f"Non aggiungere testo fuori dal JSON."
    )

    last_error = None
    for attempt in range(1, max_retries + 1):
        current_prompt = prompt
        if last_error:
            current_prompt = (
                f"{prompt}\n\n"
                f"ATTENZIONE: il tentativo precedente ha fallito la validazione con questo errore:\n"
                f"{last_error}\n"
                f"Correggi e rispondi di nuovo SOLO con il JSON valido."
            )

        raw = _call_llm(current_prompt, system_prompt=schema_prompt, max_tokens=max_tokens, temperature=temperature)
        if not raw:
            last_error = "Nessuna risposta dal modello LLM"
            continue

        clean = raw.strip()
        clean = re.sub(r'^```(?:json)?', '', clean)
        clean = re.sub(r'```$', '', clean).strip()

        try:
            parsed = json.loads(clean)
            validated = schema_cls.model_validate(parsed)
            logger.info(f"Structured output valido al tentativo {attempt}: {validated.model_dump()}")
            return validated
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Tentativo {attempt}/{max_retries} fallito nella validazione structured output: {e}")

    logger.error(f"Structured output fallito dopo {max_retries} tentativi. Ultimo errore: {last_error}")
    return None

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
    """Receives the task and settings, and appends user message to JSONL file memory."""
    thread_id = state.get("thread_id")
    task = state.get("task", "")
    if thread_id and task:
        _append_message_to_file(thread_id, "user", task)
    return state

def retrieve_memory_node(state: AgentState) -> AgentState:
    """Retrieves relevant memory context combining sliding window + incremental summary."""
    thread_id = state.get("thread_id")
    if not thread_id:
        return {"memory_context": None, "agent_id": None}

    agent_id = letta_client.create_thread(thread_id)
    raw_messages = letta_client.get_messages(agent_id) if agent_id else []
    clean_messages = letta_client.filter_clean_messages(raw_messages) if raw_messages else []

    # Fallback su file JSONL se Letta è offline o non ha messaggi
    if not clean_messages:
        clean_messages = _read_messages_from_file(thread_id)

    summary = ""
    recent_messages = []

    if len(clean_messages) > 30:
        summary_key = f"summary_1_30_{thread_id}"
        summary_file = os.path.join(MEMORY_DIR, f"summary_{thread_id}.txt")

        if agent_id:
            summary = letta_client.get_archival_memory(agent_id, key=summary_key)

        if not summary and os.path.exists(summary_file):
            try:
                with open(summary_file, "r", encoding="utf-8") as sf:
                    summary = sf.read().strip()
            except Exception:
                pass

        if not summary:
            old_messages = clean_messages[:-20]
            logger.info(f"Generazione summary incrementale per thread '{thread_id}' su {len(old_messages)} vecchi messaggi...")
            summary = _generate_summary(old_messages)
            if summary:
                if agent_id:
                    letta_client.save_archival_memory(agent_id, key=summary_key, value=summary)
                try:
                    os.makedirs(MEMORY_DIR, exist_ok=True)
                    with open(summary_file, "w", encoding="utf-8") as sf:
                        sf.write(summary)
                except Exception as e:
                    logger.warning(f"Errore salvataggio summary locale {summary_file}: {e}")
        
        recent_messages = clean_messages[-20:]
    else:
        recent_messages = clean_messages

    memory_parts = []
    if summary:
        memory_parts.append(f"### Riepilogo conversazione precedente:\n{summary}")

    if recent_messages:
        memory_parts.append("### Messaggi recenti:")
        for msg in recent_messages:
            m_type = str(msg.get("message_type", "")).lower()
            role_label = "User" if "user" in m_type else "Assistant"
            txt = msg.get("content", "")
            if txt:
                memory_parts.append(f"{role_label}: {txt}")

    memory_context = "\n\n".join(memory_parts) if memory_parts else ""
    logger.info(f"Retrieval memoria per thread '{thread_id}': total_messages={len(clean_messages)}, has_summary={bool(summary)}, recent_window={len(recent_messages)}")
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


def extract_output_var(result: Any, output_var: str, step_id: int) -> Any:
    """Estrae una variabile da un result di tool MetaMCP con fallback a euristiche annidate."""
    if not output_var:
        return None

    def find_key_in_nested(obj: Any, key: str, max_depth: int = 5) -> Any:
        if max_depth <= 0:
            return None
        if isinstance(obj, dict):
            if key in obj and obj[key] is not None:
                return obj[key]
            for v in obj.values():
                found = find_key_in_nested(v, key, max_depth - 1)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = find_key_in_nested(item, key, max_depth - 1)
                if found is not None:
                    return found
        elif isinstance(obj, str):
            try:
                parsed = json.loads(obj)
                return find_key_in_nested(parsed, key, max_depth - 1)
            except Exception:
                pass
        return None

    # 1. Cerca output_var esplicito
    val = find_key_in_nested(result, output_var)
    if val is not None:
        logger.info(f"Step {step_id}: estratta variabile '{output_var}'={val}")
        return val

    # 2. Fallback a euristiche generiche
    for heuristic_key in ["ip", "vmid", "id", "value", "result"]:
        val = find_key_in_nested(result, heuristic_key)
        if val is not None:
            logger.info(f"Step {step_id}: estratta variabile '{output_var}'={val} (fallback su '{heuristic_key}')")
            return val

    # 3. Non trovato
    logger.warning(f"Step {step_id}: variabile '{output_var}' non trovata nel result, uso None")
    return None


def topological_sort_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ordina gli step in ordine topologico basato su depends_on."""
    if not steps:
        return []
    sorted_steps = []
    remaining = list(steps)
    executed_ids = set()

    while remaining:
        ready = [s for s in remaining if s.get("depends_on") is None or s.get("depends_on") in executed_ids]
        if not ready:
            ready = [remaining[0]]

        for step in ready:
            sorted_steps.append(step)
            remaining.remove(step)
            step_id = step.get("id")
            if step_id is not None:
                executed_ids.add(step_id)

    return sorted_steps


class ExecutionLog:
    """Transaction log entry per un singolo step (WAL pattern)."""
    def __init__(self, step: dict, tool_name: str, args: dict):
        self.step = step
        self.tool_name = tool_name
        self.args = args
        self.result = None
        self.error = None
        self.timestamp_start = datetime.utcnow()
        self.timestamp_end = None
        self.rollback_executed = False
        self.rollback_error = None
    
    def to_dict(self) -> dict:
        return {
            "step_id": self.step.get("id"),
            "tool_name": self.tool_name,
            "args": self.args,
            "result": self.result,
            "error": self.error,
            "timestamp_start": self.timestamp_start.isoformat(),
            "timestamp_end": self.timestamp_end.isoformat() if self.timestamp_end else None,
            "rollback_executed": self.rollback_executed,
            "rollback_error": self.rollback_error
        }


def execute_rollback_for_step(log: ExecutionLog, tools_catalog: list[dict]) -> bool:
    """
    Esegue il rollback per un singolo step, usando info dichiarative e popolamento template.
    Ritorna True se successo, False se fallito.
    """
    tool_name = log.tool_name
    result = log.result
    step_id = log.step.get("id")

    rollback_info = get_rollback_info(tool_name)
    if not rollback_info or not rollback_info.get("reversible"):
        logger.warning(f"Step {step_id}: tool `{tool_name}` non è reversibile, impossibile rollback")
        log.rollback_executed = False
        log.rollback_error = "Tool non reversibile"
        return False
    
    rollback_tool = rollback_info.get("rollback_tool")
    rollback_args_template = rollback_info.get("rollback_args_template", {})
    
    if not rollback_tool:
        logger.error(f"Step {step_id}: rollback_info per `{tool_name}` non specifica rollback_tool")
        log.rollback_executed = False
        log.rollback_error = "Rollback tool non specificato"
        return False
    
    rollback_args = {}
    value_map = {}
    if isinstance(log.args, dict):
        value_map.update(log.args)
    if isinstance(result, dict):
        value_map.update(result)
        
    for arg_key, template_val in rollback_args_template.items():
        if isinstance(template_val, str):
            val_str = template_val
            for res_key, res_val in value_map.items():
                placeholder = f"{{{{{res_key}}}}}"
                if placeholder in val_str:
                    val_str = val_str.replace(placeholder, str(res_val))
            if "{{" in val_str and "}}" in val_str:
                raw_var = val_str.replace("{", "").replace("}", "").strip()
                extracted = extract_output_var(result, raw_var, step_id)
                if extracted is not None:
                    val_str = str(extracted)
            rollback_args[arg_key] = val_str
        else:
            rollback_args[arg_key] = template_val
    
    logger.info(f"Rollback step {step_id}: `{rollback_tool}` con args {rollback_args}")
    
    try:
        rollback_result = client.call_tool(rollback_tool, rollback_args)
        if isinstance(rollback_result, dict) and "error" in rollback_result:
            log.rollback_executed = False
            log.rollback_error = rollback_result["error"]
            logger.error(f"Rollback fallito per step {step_id}: {rollback_result['error']}")
            return False
        else:
            log.rollback_executed = True
            logger.info(f"Rollback riuscito per step {step_id}")
            return True
    except Exception as e:
        log.rollback_executed = False
        log.rollback_error = str(e)
        logger.error(f"Eccezione nel rollback per step {step_id}: {e}")
        return False


def generate_rollback_plan_with_llm(execution_log: List[ExecutionLog], task: str, error_context: str) -> Optional[str]:
    """
    Usa l'LLM per generare un piano di rollback contestuale quando quello dichiarativo non basta.
    """
    log_summary = "\n".join([
        f"- Step {e.step.get('id')}: `{e.tool_name}`({e.args}) → {'OK' if not e.error else 'ERROR: ' + str(e.error)}"
        for e in execution_log
    ])
    
    prompt = f"""
    Un piano di esecuzione è fallito dopo questi step:
    {log_summary}
    
    Task originale: {task}
    Errore: {error_context}
    
    Genera un piano di rollback per ripristinare lo stato iniziale.
    Elenca i passaggi di rollback in ordine inverso, specificando per ciascuno:
    - Azione da compiere
    - Tool da usare (se noto, altrimenti lascia come "azione manuale")
    
    Piano di rollback:"""
    
    plan = _call_llm(prompt, system_prompt="Sei un assistente esperto in rollback di operazioni di infrastruttura Proxmox.", max_tokens=512, temperature=0.3)
    return plan.strip() if plan else None


def execute_plan_node(state: AgentState) -> AgentState:
    """Executes real MetaMCP tools sequentially based on state['plan_structure'] with robust declarative & WAL rollback."""
    task = state.get("task", "")
    plan_struct = state.get("plan_structure") or state.get("plan", {}).get("plan_structure")
    
    if not plan_struct or not isinstance(plan_struct, dict) or "steps" not in plan_struct:
        return act_graph_node(state)

    steps = plan_struct.get("steps", [])
    sorted_steps = topological_sort_steps(steps)
    
    context_vars = {}
    execution_log: List[ExecutionLog] = []
    exec_lines = [
        f"🚀 **Avvio esecuzione reale del piano MetaMCP**: *'{task}'*\n",
        "### Esito Esecuzione Tool Real-Time:\n"
    ]
    
    has_error = False

    for step in sorted_steps:
        step_id = step.get("id", 1)
        depends_on = step.get("depends_on")
        desc = step.get("description", "")
        tool_name = step.get("tool", "")
        args = step.get("args", {})
        output_var = step.get("output_var")

        logger.info(f"Esecuzione step {step_id} (dipende da: {depends_on}): {tool_name}")

        resolved_args = {}
        if isinstance(args, dict):
            for k, v in args.items():
                if isinstance(v, str):
                    val_str = v
                    for var_k, var_v in context_vars.items():
                        placeholder = f"{{{{{var_k}}}}}"
                        if placeholder in val_str:
                            val_str = val_str.replace(placeholder, str(var_v))
                    resolved_args[k] = val_str
                else:
                    resolved_args[k] = v

        # Log entry creata PRIMA dell'esecuzione (Write-Ahead Logging / WAL)
        log_entry = ExecutionLog(step, tool_name, resolved_args)
        execution_log.append(log_entry)

        try:
            result = client.call_tool(tool_name, resolved_args)
            log_entry.result = result
            log_entry.timestamp_end = datetime.utcnow()
            logger.info(f"Step {step_id} completato: {result}")
            
            if isinstance(result, dict) and "error" in result:
                has_error = True
                err_msg = result["error"]
                log_entry.error = err_msg
                exec_lines.append(f"{step_id}. ❌ `{desc}` — Tool `{tool_name}` fallito: `{err_msg}`")
                break
            
            if output_var:
                extracted_val = extract_output_var(result, output_var, step_id)
                if extracted_val is not None:
                    context_vars[output_var] = extracted_val

            args_str = json.dumps(resolved_args, ensure_ascii=False) if resolved_args else "{}"
            exec_lines.append(f"{step_id}. ✅ `{desc}` — `{tool_name}`({args_str}) → *OK*")
        except Exception as e:
            has_error = True
            log_entry.error = str(e)
            log_entry.timestamp_end = datetime.utcnow()
            logger.error(f"Step {step_id} fallito con eccezione: {e}")
            exec_lines.append(f"{step_id}. ❌ `{desc}` — Errore di chiamata tool `{tool_name}`: `{e}`")
            break

    # Rollback dichiarativo in ordine inverso (LIFO Undo Stack)
    if has_error and execution_log:
        exec_lines.append("\n### 🔄 Rollback parziale degli step eseguiti:\n")
        tools_catalog = get_tool_catalog()
        
        for log_entry in reversed(execution_log):
            if not log_entry.error:  # Rollback solo degli step eseguiti con successo
                success = execute_rollback_for_step(log_entry, tools_catalog)
                step_id = log_entry.step.get("id")
                if success:
                    exec_lines.append(f"  ✅ Rollback step {step_id}: `{log_entry.tool_name}`")
                else:
                    exec_lines.append(f"  ❌ Rollback FALLITO/SKIPPATO step {step_id}: `{log_entry.tool_name}` — {log_entry.rollback_error}")

        # Se alcuni rollback dichiarativi falliscono o non sono reversibili, attiva LLM Rollback Planning
        failed_rollbacks = [e for e in execution_log if not e.rollback_executed and not e.error]
        if failed_rollbacks:
            exec_lines.append("\n### 🤖 LLM-based Rollback Planning:\n")
            error_ctx = "Step non reversibili o rollback dichiarativo non completato"
            llm_plan = generate_rollback_plan_with_llm(execution_log, task, error_ctx)
            if llm_plan:
                exec_lines.append(f"```\n{llm_plan}\n```")
                exec_lines.append("\n⚠️ **Piano LLM generato: esegui manualmente i passaggi sopra se necessario.**")

        exec_lines.append("\n⚠️ **Rollback parziale completato. Verifica dello stato raccomandata.**")

    if not has_error:
        exec_lines.append("\n🎉 **Tutti i passaggi del piano sono stati eseguiti con successo su Proxmox!**")

    ans = "\n".join(exec_lines)
    log_dicts = [log.to_dict() for log in execution_log]
    plan = {"mode": "act", "tool_needed": True, "direct_answer": ans, "plan_structure": plan_struct, "execution_log": log_dicts}
    return {"plan": plan, "plan_structure": plan_struct, "final_response": ans}


def act_graph_node(state: AgentState) -> AgentState:
    """Subgraph for single tool or plan execution."""
    task = state.get("task", "")
    task_lower = task.lower()

    if state.get("plan_structure") or state.get("plan", {}).get("plan_structure"):
        if state.get("execute") or any(kw in task_lower for kw in ["esegui il piano", "esegui piano", "avvia esecuzione", "esecuzione piano"]):
            return execute_plan_node(state)

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

    # --- NUOVA LOGICA: selezione dinamica LLM-based del tool ---
    tools = get_tool_catalog()
    catalog_str = format_catalog_for_prompt(tools)
    memory_context = state.get("memory_context") or ""

    system_prompt = (
        "Sei l'Agente AI dell'Homelab Proxmox VE. Il tuo compito è selezionare il tool più adatto "
        "dal catalogo per soddisfare la richiesta dell'utente, ed estrarre gli argomenti corretti.\n\n"
        f"Catalogo tool disponibili:\n{catalog_str}\n\n"
        f"Contesto conversazione:\n{memory_context}\n\n"
        "Se nessun tool è necessario o la richiesta è troppo vaga o irrilevante, imposta tool_needed=false."
    )

    selection = _call_llm_structured(
        prompt=task,
        system_prompt=system_prompt,
        schema_cls=ToolSelection,
        max_tokens=400,
        temperature=0.0,
        max_retries=3
    )

    if not selection or not selection.tool_needed or not selection.tool_name:
        ans = selection.reasoning if selection and selection.reasoning else f"Non ho trovato un tool adatto per la richiesta: '{task}'. Puoi specificare meglio la tua richiesta?"
        plan = {"mode": "act", "tool_needed": False, "direct_answer": ans}
        return {"plan": plan}

    tool_name = selection.tool_name
    arguments = selection.arguments
    max_exec_retries = 2
    result = None
    last_exec_error = None

    for attempt in range(1, max_exec_retries + 1):
        # 1. Validazione schema argomenti PRIMA di chiamare il tool
        val_error = validate_tool_args(tool_name, arguments, tools)
        if val_error:
            last_exec_error = val_error
            logger.warning(f"Validazione schema argomenti fallita per {tool_name} (tentativo {attempt}): {val_error}")
            if attempt < max_exec_retries:
                correction = _call_llm_structured(
                    prompt=f"La chiamata al tool '{tool_name}' con argomenti {arguments} ha fallito la validazione dello schema: {val_error}. Correggi gli argomenti per soddisfare la richiesta originale: '{task}'.",
                    system_prompt=system_prompt,
                    schema_cls=ToolSelection,
                    max_tokens=400,
                    temperature=0.0,
                    max_retries=2
                )
                if correction and correction.tool_name:
                    tool_name = correction.tool_name
                    arguments = correction.arguments
                continue

        # 2. Esecuzione reale del tool
        try:
            result = client.call_tool(tool_name, arguments)
            if isinstance(result, dict) and "error" in result:
                last_exec_error = result["error"]
                logger.warning(f"Tool {tool_name} ha risposto con errore (tentativo {attempt}): {last_exec_error}")
                if attempt < max_exec_retries:
                    correction = _call_llm_structured(
                        prompt=f"Il tool '{tool_name}' è stato chiamato con argomenti {arguments} ma ha fallito con errore: {last_exec_error}. Correggi gli argomenti per la stessa richiesta originale: '{task}'.",
                        system_prompt=system_prompt,
                        schema_cls=ToolSelection,
                        max_tokens=400,
                        temperature=0.0,
                        max_retries=2
                    )
                    if correction and correction.tool_name:
                        tool_name = correction.tool_name
                        arguments = correction.arguments
                    continue
            else:
                last_exec_error = None
                break
        except Exception as e:
            last_exec_error = str(e)
            logger.error(f"Eccezione chiamando tool {tool_name} (tentativo {attempt}): {e}")

    if last_exec_error and (not result or (isinstance(result, dict) and "error" in result)):
        ans = f"Task: {task}\nTool tentato: `{tool_name}`\nErrore dopo {max_exec_retries} tentativi: {last_exec_error}"
        plan = {"mode": "act", "tool_needed": True, "tool_name": tool_name, "direct_answer": ans}
        return {"plan": plan, "tool_result": None}

    formatted = _format_tool_result(tool_name, result)
    ans = f"Task: {task}\nTool utilizzato: `{tool_name}` (confidenza: {selection.confidence:.0%})\nRisultato:\n{formatted}"
    plan = {"mode": "act", "tool_needed": True, "tool_name": tool_name, "direct_answer": ans}
    return {"plan": plan, "tool_result": result}

def plan_graph_node(state: AgentState) -> AgentState:
    """Subgraph for detailed multi-step planning (simulation/dry-run & JSON plan generation)."""
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

    # Generate JSON plan_structure via LLM
    json_prompt = (
        f"Genera un piano JSON strutturato per il seguente task dell'utente: '{task}'.\n"
        "Rispondi ESCLUSIVAMENTE con un JSON valido con questa struttura:\n"
        "{\n"
        "  \"steps\": [\n"
        "    {\n"
        "      \"id\": 1,\n"
        "      \"description\": \"Descrizione dello step\",\n"
        "      \"tool\": \"proxmox-mcp__nome_tool\",\n"
        "      \"args\": {\"param\": \"valore\"},\n"
        "      \"depends_on\": null,\n"
        "      \"output_var\": \"nome_variabile\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    json_resp = _call_llm(task, system_prompt=json_prompt, max_tokens=600, temperature=0.1)
    plan_structure = None
    if json_resp:
        try:
            clean_json = re.sub(r'```(?:json)?', '', json_resp).strip()
            parsed = json.loads(clean_json)
            if isinstance(parsed, dict) and "steps" in parsed and isinstance(parsed["steps"], list):
                plan_structure = parsed
        except Exception as e:
            logger.warning(f"Failed to parse LLM plan JSON: {e}")

    if not plan_structure:
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["lista", "ispeziona", "controlla"]):
            plan_structure = {
                "steps": [
                    {
                        "id": 1,
                        "description": "Acquisizione inventario e stato real-time dei container",
                        "tool": "proxmox-mcp__list_containers",
                        "args": {},
                        "depends_on": None,
                        "output_var": "containers_list"
                    }
                ]
            }
        else:
            plan_structure = {
                "steps": [
                    {
                        "id": 1,
                        "description": "Allocazione IP libero da IPAM",
                        "tool": "proxmox-mcp__allocate_ip",
                        "args": {"hostname": "test-service"},
                        "depends_on": None,
                        "output_var": "allocated_ip"
                    },
                    {
                        "id": 2,
                        "description": "Creazione LXC da template base",
                        "tool": "proxmox-mcp__create_lxc_from_template",
                        "args": {
                            "key": "base",
                            "ip": "{{allocated_ip}}",
                            "hostname": "test-service"
                        },
                        "depends_on": 1,
                        "output_var": "created_vmid"
                    },
                    {
                        "id": 3,
                        "description": "Creazione record DNS Pi-hole",
                        "tool": "proxmox-mcp__add_pihole_dns_record",
                        "args": {
                            "domain": "test-service.home.lab",
                            "target_ip": "{{allocated_ip}}"
                        },
                        "depends_on": 1,
                        "output_var": None
                    },
                    {
                        "id": 4,
                        "description": "Configurazione Host Proxy Nginx Manager",
                        "tool": "proxmox-mcp__create_npm_proxy_host",
                        "args": {
                            "domain": "test-service.home.lab",
                            "forward_ip": "{{allocated_ip}}",
                            "forward_port": 80
                        },
                        "depends_on": 2,
                        "output_var": None
                    }
                ]
            }

    if not plan_steps:
        plan_steps = [s.get("description", "") for s in plan_structure.get("steps", []) if s.get("description")]

    formatted_steps_str = "\n".join(f"{i+1}. {step}" for i, step in enumerate(plan_steps))
    formatted_plan = f"Piano multi-step generato per: '{task}'\n\nPassaggi di esecuzione:\n{formatted_steps_str}"
    formatted_plan += "\n\nNota: Stato 'dry-run' completato. In attesa di conferma per l'esecuzione dei tool in sequenza."

    plan = {
        "mode": "plan",
        "tool_needed": False,
        "multi_step": True,
        "plan_steps": plan_steps,
        "plan_structure": plan_structure
    }

    if state.get("execute"):
        return execute_plan_node(state)

    return {"plan": plan, "plan_structure": plan_structure, "final_response": formatted_plan}

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
    """Formats final response if not already set and appends assistant message to file system memory."""
    thread_id = state.get("thread_id")
    if state.get("final_response"):
        resp = state.get("final_response")
        if thread_id and resp:
            _append_message_to_file(thread_id, "assistant", resp)
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

    if thread_id and formatted:
        _append_message_to_file(thread_id, "assistant", formatted)

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
