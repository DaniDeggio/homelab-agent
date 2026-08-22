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
    call_llm_structured_fn: Any = None,
    thread_id: Optional[str] = None
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
            ans_res = call_llm_fn(task, system_prompt=sys_prompt, reasoning_budget=policy.reasoning_budget)
            if ans_res:
                ans = ans_res.get("content", "")
                reasoning = ans_res.get("reasoning_content", "")
                return {"final_response": ans, "execution_trace": [], "reasoning_content": reasoning}
        return {"final_response": f"Ho ricevuto la tua richiesta: '{task}'.", "execution_trace": [], "reasoning_content": None}

    catalog_str = format_catalog_for_prompt(available_tools)
    history_observations = []
    
    # --- Fase 3.4: cache/deduplicazione risultati tool identici nello stesso run ---
    call_cache: Dict[str, Any] = {}

    for step_id in range(1, policy.max_tool_calls + 1):
        obs_context = "\n".join(history_observations) if history_observations else "Nessuna azione eseguita finora."
        
        now_str = datetime.now().strftime('%A %d %B %Y, %H:%M:%S')
        base_system_prompt = (
            f"Data e Ora Corrente del Sistema: {now_str}\n"
            f"Sei l'Agente AI dell'Homelab Proxmox (modalità: {mode.upper()}).\n"
        )

        tool_system_prompt = base_system_prompt + (
            f"Catalogo tool disponibili per questa modalità:\n{catalog_str}\n\n"
            f"Contesto memoria conversazionale:\n{memory_context or ''}\n\n"
            f"Storico azioni eseguite in questo turno:\n{obs_context}\n\n"
            "REGOLE IMPORTANTI PER LE QUERY DI RICERCA WEB:\n"
            "- NON aggiungere anni passati (es. '2024 2025') alle query di ricerca a meno che l'utente non lo richieda esplicitamente.\n"
            "- Usa query naturali e concise (es. 'Artemis II mission results' invece di 'Artemis 2 mission results 2024 2025').\n"
            "- Per notizie recenti usa termini come 'latest' o 'aggiornamento' senza specificare anni.\n"
            "- Se una ricerca web ha restituito 'Nessun risultato trovato', NON ripetere la stessa identica query. "
            "Riformula COMPLETAMENTE la query: cambia lingua (italiano<->inglese), usa sinonimi, semplifica, o prova termini diversi.\n"
            f"Valuta attentamente se è necessario utilizzare un tool per rispondere alla richiesta. "
            f"REGOLA FONDAMENTALE: Se la richiesta riguarda eventi futuri, previsioni meteo, orari, date esatte (es. eclissi) o informazioni che non puoi conoscere con certezza, "
            f"NON affidarti alla tua memoria interna. DEVI restituire tool_needed=True e usare il tool 'web_search' per ottenere dati reali e aggiornati.\n"
            f"Se la risposta richiede azioni sul sistema (es. Proxmox, file, container), DEVI restituire tool_needed=True e specificare il tool corretto.\n"
            f"Se la risposta può essere fornita con certezza assoluta usando la tua conoscenza interna, restituisci tool_needed=False.\n"
            f"CHIAMATE PARALLELE: se ti servono le informazioni di PIÙ tool di sola lettura (es. lista container + stato DNS) e sono indipendenti tra loro, "
            f"usa 'parallel_calls' con una lista di {{tool_name, arguments}} invece di chiamate sequenziali.\n"
            f"IMPORTANTE: Se devi ragionare, fallo liberamente. Il sistema processerà automaticamente il tuo reasoning_content. FORNISCI LA RISPOSTA FINALE UTILE E COMPLETA PER L'UTENTE in 'final_answer'."
        )

        if not call_llm_structured_fn:
            break

        selection = call_llm_structured_fn(
            prompt=task,
            system_prompt=tool_system_prompt,
            schema_cls=ToolSelection,
            max_tokens=600,
            temperature=0.0,
            max_retries=2,
            reasoning_budget=policy.reasoning_budget
        )

        if not selection or (not selection.tool_needed and not selection.parallel_calls) or not selection.tool_name:
            # 1. Se l'LLM ha fornito un final_answer esplicito
            if selection and selection.final_answer and len(selection.final_answer.strip()) > 10:
                final_ans = selection.final_answer.strip()
                reasoning_content = selection.reasoning or None
            # 2. Se abbiamo eseguito dei tool ed abbiamo delle osservazioni, sintetizziamo la risposta per l'utente
            elif history_observations and call_llm_fn:
                summary_system_prompt = base_system_prompt + (
                    "Sei in fase di risposta finale all'utente dopo aver eseguito dei tool.\n"
                    "Il tuo compito è sintetizzare le informazioni ottenute dai tool o dalle azioni eseguite in una risposta fluida, completa ed esaustiva in italiano.\n"
                    "NON generare codice JSON, NON richiamare alcun tool e NON usare la sintassi dei tool in questo step."
                )
                obs_text = "\n".join(history_observations)
                if len(obs_text) > config.TRUNCATION_LIMIT:
                    obs_text = obs_text[:config.TRUNCATION_LIMIT] + "\n... [osservazioni troncate per brevità]"
                summary_prompt = (
                    f"Task utente: '{task}'\n\n"
                    f"Storico azioni e risultati dei tool eseguiti:\n{obs_text}\n\n"
                    f"Fornisci una risposta finale all'utente, rigorosamente in lingua ITALIANA. "
                    f"La risposta deve essere discorsiva, dettagliata ed esaustiva, non limitarti a un riassunto telegrafico. "
                    f"Spiega i dettagli rilevanti in modo naturale. "
                    f"Se sono stati usati tool di ricerca (es. web_search), cita o spiega le informazioni trovate in modo chiaro e completo."
                )
                syn_res = call_llm_fn(summary_prompt, system_prompt=summary_system_prompt, reasoning_budget=policy.reasoning_budget) if call_llm_fn else None
                syn_ans = syn_res.get("content", "") if syn_res else ""
                reasoning_content = syn_res.get("reasoning_content", "") if syn_res else ""
                final_ans = syn_ans.strip() if (syn_ans and syn_ans.strip()) else (
                    selection.reasoning if (selection and selection.reasoning) else (
                        "Il modello ha effettuato il ragionamento ma non ha generato una risposta finale." if reasoning_content else "Operazione completata con successo."
                    )
                )
            # 3. Se la richiesta non richiede tool (es. domande concettuali), generiamo una risposta diretta
            elif call_llm_fn:
                direct_system_prompt = base_system_prompt + (
                    "Sei in fase di dialogo diretto con l'utente.\n"
                    "Rispondi in modo naturale, esaustivo e chiaro alla richiesta in italiano.\n"
                    "NON generare codice JSON e NON cercare di utilizzare o richiamare alcun tool."
                )
                direct_prompt = (
                    f"Rispondi in modo completo, chiaro ed esaustivo alla seguente domanda dell'utente in italiano.\n"
                    f"Domanda: '{task}'\n"
                    f"Contesto memoria:\n{memory_context or ''}"
                )
                syn_res = call_llm_fn(direct_prompt, system_prompt=direct_system_prompt, reasoning_budget=policy.reasoning_budget)
                syn_ans = syn_res.get("content", "") if syn_res else ""
                reasoning_content = syn_res.get("reasoning_content", "") if syn_res else ""
                final_ans = syn_ans.strip() if (syn_ans and syn_ans.strip()) else (
                    selection.reasoning if (selection and selection.reasoning) else (
                        "Il modello ha effettuato il ragionamento ma non ha generato una risposta finale." if reasoning_content else "Richiesta completata."
                    )
                )
            else:
                final_ans = selection.reasoning if (selection and selection.reasoning) else "Richiesta completata."
                reasoning_content = None

            return {"final_response": final_ans, "execution_trace": execution_trace, "reasoning_content": reasoning_content}

        # --- Fase 3.3: chiamate parallele per tool read-only indipendenti ---
        if selection.parallel_calls and len(selection.parallel_calls) > 1:
            import guardrails as _gr
            readonly_calls = [
                c for c in selection.parallel_calls
                if isinstance(c, dict) and c.get("tool_name") and _gr.classify_tool(c["tool_name"]) == "safe"
            ]
            if len(readonly_calls) > 1:
                logger.info(f"Step {step_id}: esecuzione parallela di {len(readonly_calls)} tool read-only")
                results = manager.execute_tools_parallel(
                    readonly_calls, policy.allowed_registries, thread_id=thread_id, mode=mode
                )
                for i, (call, res) in enumerate(zip(readonly_calls, results)):
                    execution_trace.append({
                        "step_id": step_id,
                        "parallel_index": i,
                        "tool_name": call["tool_name"],
                        "args": call.get("arguments", {}),
                        "result": res,
                        "reasoning": selection.reasoning,
                        "parallel": True,
                        "error": res.get("error") if isinstance(res, dict) else None
                    })
                    res_str = json.dumps(res, ensure_ascii=False) if isinstance(res, (dict, list)) else str(res)
                    history_observations.append(f"Step {step_id}.{i} [parallelo]: {call['tool_name']}({call.get('arguments')}) -> {res_str}")
                continue

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

        # Esecuzione del tool via Registry Manager (con guardrail + approval + audit)
        # --- Fase 3.4: deduplicazione chiamate identiche ---
        import guardrails as _gr
        cache_key = f"{tool_name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"
        is_readonly = _gr.classify_tool(tool_name) == "safe"
        if is_readonly and cache_key in call_cache:
            logger.info(f"Step {step_id}: '{tool_name}' già eseguito con stessi argomenti: riuso risultato cached")
            tool_res = call_cache[cache_key]
            execution_trace.append({
                "step_id": step_id,
                "tool_name": tool_name,
                "args": arguments,
                "result": tool_res,
                "reasoning": selection.reasoning if selection else None,
                "cached": True,
                "error": None
            })
            history_observations.append(f"Step {step_id}: {tool_name}({arguments}) -> [risultato in cache da step precedente]")
            continue

        tool_res = manager.execute_tool(tool_name, arguments, policy.allowed_registries, thread_id=thread_id, mode=mode)

        # Se serve approvazione utente: registra la pending e interrompi il loop in attesa
        if isinstance(tool_res, dict) and tool_res.get("approval_required"):
            execution_trace.append({
                "step_id": step_id,
                "tool_name": tool_name,
                "args": arguments,
                "reasoning": selection.reasoning if selection else None,
                "approval_required": True,
                "request_id": tool_res.get("request_id"),
                "message": tool_res.get("message"),
                "error": None
            })
            history_observations.append(
                f"Step {step_id}: {tool_name} richiede approvazione utente (richiesta {tool_res.get('request_id')}). "
                f"In attesa di conferma. Non ripetere la chiamata."
            )
            break
        
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

        # Cache solo per tool read-only (risultati riproducibili)
        if is_readonly and not is_error:
            call_cache[cache_key] = tool_res

        res_str = json.dumps(tool_res, ensure_ascii=False) if isinstance(tool_res, (dict, list)) else str(tool_res)
        history_observations.append(f"Step {step_id}: {tool_name}({arguments}) -> {res_str}")

        if is_error:
            logger.warning(f"Step {step_id}: tool '{tool_name}' restituito errore: {err_msg}")

    # Se abbiamo raggiunto il limite di step, generiamo una sintesi finale
    obs_text = "\n".join(history_observations)
    if len(obs_text) > config.TRUNCATION_LIMIT:
        obs_text = obs_text[:config.TRUNCATION_LIMIT] + "\n... [osservazioni troncate per brevità]"

    now_str = datetime.now().strftime('%A %d %B %Y, %H:%M:%S')
    summary_system_prompt = (
        f"Data e Ora Corrente del Sistema: {now_str}\n"
        f"Sei l'Agente AI dell'Homelab Proxmox (modalità: {mode.upper()}).\n"
        "Sei in fase di risposta finale all'utente dopo aver eseguito dei tool.\n"
        "Il tuo compito è sintetizzare le informazioni ottenute dai tool o dalle azioni eseguite in una risposta fluida, completa ed esaustiva in italiano.\n"
        "NON generare codice JSON, NON richiamare alcun tool e NON usare la sintassi dei tool in questo step."
    )
    summary_prompt = (
        f"Task utente: '{task}'\n\n"
        f"Sulla base delle seguenti azioni e ricerche eseguite:\n{obs_text}\n\n"
        f"Fornisci la risposta finale completa e ben formattata in italiano per l'utente."
    )
    syn_res = call_llm_fn(summary_prompt, system_prompt=summary_system_prompt, reasoning_budget=policy.reasoning_budget) if call_llm_fn else None
    syn_ans = syn_res.get("content", "") if syn_res else ""
    reasoning_content = syn_res.get("reasoning_content", "") if syn_res else ""
    
    if not syn_ans or not syn_ans.strip():
        # Fallback sicuro: se l'LLM di sintesi fallisce, non restituire mai None!
        syn_ans = "Il modello ha effettuato il ragionamento ma non ha generato una risposta testuale." if reasoning_content else "Informazioni recuperate con successo dai tool di ricerca. Consulta i dettagli nei log di esecuzione."

    return {"final_response": syn_ans.strip(), "execution_trace": execution_trace, "reasoning_content": reasoning_content}
