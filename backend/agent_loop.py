import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from mode_policy import get_mode_policy
from registry.manager import get_registry_manager
from tool_schemas import ToolSelection, validate_tool_args
from tool_catalog import format_catalog_for_prompt
import config

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
            now_str = datetime.now().strftime('%A %d %B %Y, %H:%M:%S')
            sys_prompt = (
                f"Data e Ora Corrente del Sistema: {now_str}\n"
                f"Sei l'Agente AI dell'Homelab Proxmox VE. Rispondi in italiano.\n"
                f"Contesto memoria:\n{memory_context or ''}"
            )
            ans = call_llm_fn(task, system_prompt=sys_prompt, reasoning_budget=policy.reasoning_budget)
            if ans:
                return {"final_response": ans, "execution_trace": []}
        return {"final_response": f"Ho ricevuto la tua richiesta: '{task}'.", "execution_trace": []}

    catalog_str = format_catalog_for_prompt(available_tools)
    history_observations = []

    for step_id in range(1, policy.max_tool_calls + 1):
        obs_context = "\n".join(history_observations) if history_observations else "Nessuna azione eseguita finora."
        
        now_str = datetime.now().strftime('%A %d %B %Y, %H:%M:%S')
        system_prompt = (
            f"Data e Ora Corrente del Sistema: {now_str}\n"
            f"Sei l'Agente AI dell'Homelab Proxmox (modalità: {mode.upper()}).\n"
            f"Catalogo tool disponibili per questa modalità:\n{catalog_str}\n\n"
            f"Contesto memoria conversazionale:\n{memory_context or ''}\n\n"
            f"Storico azioni eseguite in questo turno:\n{obs_context}\n\n"
            "REGOLE IMPORTANTI PER LE QUERY DI RICERCA WEB:\n"
            "- NON aggiungere anni passati (es. '2024 2025') alle query di ricerca a meno che l'utente non lo richieda esplicitamente.\n"
            "- Usa query naturali e concise (es. 'Artemis II mission results' invece di 'Artemis 2 mission results 2024 2025').\n"
            "- Per notizie recenti usa termini come 'latest' o 'aggiornamento' senza specificare anni.\n"
            "- Se una ricerca web ha restituito 'Nessun risultato trovato', NON ripetere la stessa identica query. "
            "Riformula COMPLETAMENTE la query: cambia lingua (italiano<->inglese), usa sinonimi, semplifica, o prova termini diversi.\n"
            "  Esempio: se 'latest Artemis mission launch status' fallisce, prova 'Artemis II NASA' o 'missione Artemis partita'.\n\n"
            "Se devi chiamare un tool, imposta tool_needed=true, seleziona tool_name e inserisci gli argomenti.\n"
            "Se la richiesta è stata soddisfatta o non servono altri tool, imposta tool_needed=false, "
            "inserisci la tua motivazione interna in 'reasoning' e FORNISCI LA RISPOSTA FINALE UTILE E COMPLETA PER L'UTENTE in 'final_answer'."
        )

        if not call_llm_structured_fn:
            break

        selection = call_llm_structured_fn(
            prompt=task,
            system_prompt=system_prompt,
            schema_cls=ToolSelection,
            max_tokens=600,
            temperature=0.0,
            max_retries=2,
            reasoning_budget=policy.reasoning_budget
        )

        if not selection or not selection.tool_needed or not selection.tool_name:
            # 1. Se l'LLM ha fornito un final_answer esplicito
            if selection and selection.final_answer and len(selection.final_answer.strip()) > 10:
                final_ans = selection.final_answer.strip()
            # 2. Se abbiamo eseguito dei tool ed abbiamo delle osservazioni, sintetizziamo la risposta per l'utente
            elif history_observations and call_llm_fn:
                obs_text = "\n".join(history_observations)
                if len(obs_text) > config.TRUNCATION_LIMIT:
                    obs_text = obs_text[:config.TRUNCATION_LIMIT] + "\n... [osservazioni troncate per brevità]"
                summary_prompt = (
                    f"Task utente: '{task}'\n\n"
                    f"Storico azioni e risultati dei tool eseguiti:\n{obs_text}\n\n"
                    f"Fornisci una risposta finale completa, chiara e ben formattata in italiano per l'utente. "
                    f"Se sono stati elencati risultati di ricerca o risorse, mostra una sintesi chiara ed esaustiva.\n"
                    f"ATTENZIONE: NON stampare il tuo processo di ragionamento (es. 'Here is a thinking process...', 'Analyze the User's Request', ecc.). Fornisci SOLO e DIRETTAMENTE la risposta finale destinata all'utente, RIGOROSAMENTE IN LINGUA ITALIANA."
                )
                syn_ans = call_llm_fn(summary_prompt, reasoning_budget=policy.reasoning_budget)
                final_ans = syn_ans.strip() if (syn_ans and syn_ans.strip()) else (
                    selection.reasoning if (selection and selection.reasoning) else "Operazione completata con successo."
                )
            # 3. Se la richiesta non richiede tool (es. domande concettuali), generiamo una risposta diretta
            elif call_llm_fn:
                direct_prompt = (
                    f"Rispondi in modo completo, chiaro ed esaustivo alla seguente domanda dell'utente in italiano.\n"
                    f"Domanda: '{task}'\n"
                    f"Contesto memoria:\n{memory_context or ''}\n\n"
                    f"ATTENZIONE: NON stampare il tuo processo di ragionamento (es. 'Here is a thinking process...', 'Analyze the User's Request', ecc.). Fornisci SOLO e DIRETTAMENTE la risposta finale destinata all'utente, RIGOROSAMENTE IN LINGUA ITALIANA."
                )
                syn_ans = call_llm_fn(direct_prompt, reasoning_budget=policy.reasoning_budget)
                final_ans = syn_ans.strip() if (syn_ans and syn_ans.strip()) else (
                    selection.reasoning if (selection and selection.reasoning) else "Richiesta completata."
                )
            else:
                final_ans = selection.reasoning if (selection and selection.reasoning) else "Richiesta completata."

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
                "reasoning": selection.reasoning if selection else None,
                "error": f"Validazione fallita: {val_error}"
            })
            history_observations.append(f"Step {step_id}: Chiamata a '{tool_name}' fallita la validazione -> {val_error}")
            continue

        # Esecuzione del tool via Registry Manager
        tool_res = manager.execute_tool(tool_name, arguments, policy.allowed_registries)
        
        is_error = isinstance(tool_res, dict) and "error" in tool_res and tool_res["error"] is not None
        err_msg = tool_res["error"] if (isinstance(tool_res, dict) and "error" in tool_res) else None
        is_sandboxed = tool_res.get("sandboxed") if isinstance(tool_res, dict) else None

        trace_entry = {
            "step_id": step_id,
            "tool_name": tool_name,
            "args": arguments,
            "result": tool_res,
            "reasoning": selection.reasoning if selection else None,
            "sandboxed": is_sandboxed,
            "error": err_msg
        }
        execution_trace.append(trace_entry)

        res_str = json.dumps(tool_res, ensure_ascii=False) if isinstance(tool_res, (dict, list)) else str(tool_res)
        history_observations.append(f"Step {step_id}: {tool_name}({arguments}) -> {res_str}")

        if is_error:
            logger.warning(f"Step {step_id}: tool '{tool_name}' restituito errore: {err_msg}")

    # Se abbiamo raggiunto il limite di step, generiamo una sintesi finale
    obs_text = "\n".join(history_observations)
    if len(obs_text) > config.TRUNCATION_LIMIT:
        obs_text = obs_text[:config.TRUNCATION_LIMIT] + "\n... [osservazioni troncate per brevità]"

    summary_prompt = (
        f"Task utente: '{task}'\n\n"
        f"Sulla base delle seguenti azioni e ricerche eseguite:\n{obs_text}\n\n"
        f"Fornisci la risposta finale completa e ben formattata in italiano per l'utente.\n"
        f"ATTENZIONE: NON stampare il tuo processo di ragionamento (es. 'Here is a thinking process...', 'Analyze the User's Request', ecc.). Fornisci SOLO e DIRETTAMENTE la risposta finale destinata all'utente, RIGOROSAMENTE IN LINGUA ITALIANA."
    )
    syn_ans = call_llm_fn(summary_prompt, reasoning_budget=policy.reasoning_budget) if call_llm_fn else None
    if not syn_ans or not syn_ans.strip():
        # Fallback sicuro: se l'LLM di sintesi fallisce, non restituire mai None!
        syn_ans = "Informazioni recuperate con successo dai tool di ricerca. Consulta i dettagli nei log di esecuzione."

    return {"final_response": syn_ans.strip(), "execution_trace": execution_trace}
