import json
import logging
from typing import Dict, Any, List, Optional
from mode_policy import get_mode_policy
from registry.manager import get_registry_manager
from tool_schemas import ToolSelection, validate_tool_args
from tool_catalog import format_catalog_for_prompt

logger = logging.getLogger("agent_loop")

def run_agent_loop(
    task: str,
    mode: str,
    memory_context: Optional[str] = None,
    call_llm_fn: Any = None,
    call_llm_structured_fn: Any = None
) -> Dict[str, Any]:
    """
    Esegue il loop ReAct autonomo in base alla ModePolicy della modalità corrente.
    - Se max_tool_calls == 0 (es. chat), risponde direttamente senza tool.
    - Altrimenti cicla: Reason -> Act -> Observe -> Loop fino al raggiungimento di max_tool_calls o final answer.
    """
    policy = get_mode_policy(mode)
    logger.info(f"Avvio agent loop per mode='{mode}' (max_tool_calls={policy.max_tool_calls}, registries={policy.allowed_registries})")

    manager = get_registry_manager()
    available_tools = manager.get_tools_for_mode(policy.allowed_registries)
    execution_trace = []

    # Se la modalità non ammette tool (es. chat) o il catalogo ammessi è vuoto
    if policy.max_tool_calls <= 0 or not available_tools:
        if call_llm_fn:
            sys_prompt = f"Sei l'Agente AI dell'Homelab Proxmox VE. Rispondi in italiano.\nContesto memoria:\n{memory_context or ''}"
            ans = call_llm_fn(task, system_prompt=sys_prompt)
            if ans:
                return {"final_response": ans, "execution_trace": []}
        return {"final_response": f"Ho ricevuto la tua richiesta: '{task}'.", "execution_trace": []}

    catalog_str = format_catalog_for_prompt(available_tools)
    history_observations = []

    for step_id in range(1, policy.max_tool_calls + 1):
        obs_context = "\n".join(history_observations) if history_observations else "Nessuna azione eseguita finora."
        
        system_prompt = (
            f"Sei l'Agente AI dell'Homelab Proxmox (modalità: {mode.upper()}).\n"
            f"Catalogo tool disponibili per questa modalità:\n{catalog_str}\n\n"
            f"Contesto memoria conversazionale:\n{memory_context or ''}\n\n"
            f"Storico azioni eseguite in questo turno:\n{obs_context}\n\n"
            "Se la richiesta è stata soddisfatta o non serve altro tool, imposta tool_needed=false e fornisci la risposta finale in reasoning."
        )

        if not call_llm_structured_fn:
            break

        selection = call_llm_structured_fn(
            prompt=task,
            system_prompt=system_prompt,
            schema_cls=ToolSelection,
            max_tokens=500,
            temperature=0.0,
            max_retries=2
        )

        if not selection or not selection.tool_needed or not selection.tool_name:
            final_ans = selection.reasoning if selection and selection.reasoning else "Richiesta completata senza ulteriori azioni."
            return {"final_response": final_ans, "execution_trace": execution_trace}

        tool_name = selection.tool_name
        arguments = selection.arguments or {}

        # Validazione argomenti
        val_error = validate_tool_args(tool_name, arguments, available_tools)
        if val_error:
            logger.warning(f"Step {step_id}: errore validazione argomenti per '{tool_name}': {val_error}")
            execution_trace.append({
                "step_id": step_id,
                "tool_name": tool_name,
                "args": arguments,
                "error": f"Validazione fallita: {val_error}"
            })
            history_observations.append(f"Step {step_id}: Chiamata a '{tool_name}' fallita la validazione -> {val_error}")
            continue

        # Esecuzione del tool via Registry Manager
        tool_res = manager.execute_tool(tool_name, arguments, policy.allowed_registries)
        
        is_error = isinstance(tool_res, dict) and "error" in tool_res
        err_msg = tool_res["error"] if is_error else None

        trace_entry = {
            "step_id": step_id,
            "tool_name": tool_name,
            "args": arguments,
            "result": tool_res,
            "error": err_msg
        }
        execution_trace.append(trace_entry)

        res_str = json.dumps(tool_res, ensure_ascii=False) if isinstance(tool_res, (dict, list)) else str(tool_res)
        history_observations.append(f"Step {step_id}: {tool_name}({arguments}) -> {res_str}")

        if is_error:
            logger.warning(f"Step {step_id}: tool '{tool_name}' restituito errore: {err_msg}")

    # Se abbiamo raggiunto il limite di step, generiamo una sintesi finale
    summary_prompt = f"Sulla base delle seguenti azioni eseguite:\n" + "\n".join(history_observations) + f"\n\nFornisci la risposta finale alla richiesta dell'utente: '{task}'"
    final_ans = call_llm_fn(summary_prompt) if call_llm_fn else "Azioni eseguite completate."
    return {"final_response": final_ans, "execution_trace": execution_trace}
