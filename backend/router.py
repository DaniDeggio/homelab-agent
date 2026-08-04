import logging
import requests
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("router")

LLAMA_CPP_URL = config.LLAMA_CPP_URL.rstrip('/')
DEFAULT_MODEL = config.DEFAULT_MODEL

def classify_mode(user_input: str, force_mode: str = None) -> str:
    """
    Classifies user input into one of 4 modes: 'chat', 'ask', 'act', 'plan'.
    Supports force_mode override and fallback to rule-matching / 'plan'.
    """
    if force_mode:
        forced = force_mode.lower().strip()
        if forced in ["chat", "ask", "act", "plan"]:
            logger.info(f"Mode forced via CLI: {forced}")
            return forced

    if not user_input:
        return "chat"

    prompt = f"""Classifica il seguente input in una di queste 4 modalità:
- chat: conversazione libera, nessun tool richiesto
- ask: query informativa, retrieval da memoria
- act: azione singola, esecuzione tool immediato
- plan: pianificazione multi-step, sequenza di tool

Input: "{user_input}"

Rispondi SOLO con una parola: chat, ask, act, o plan."""

    url = f"{LLAMA_CPP_URL}/chat/completions"
    payload = {
        "model": DEFAULT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
        "temperature": 0.0
    }

    try:
        res = requests.post(url, json=payload, timeout=4)
        if res.status_code == 200:
            content = res.json()["choices"][0]["message"].get("content", "").strip().lower()
            for mode in ["chat", "ask", "act", "plan"]:
                if mode in content:
                    logger.info(f"Neural router classified mode={mode} for input='{user_input}'")
                    return mode
    except Exception as e:
        logger.warning(f"Neural router call skipped ({e}). Using rule-based fallback.")

    input_lower = user_input.lower()
    if any(kw in input_lower for kw in ["ciao", "salut", "chi sei", "buongiorno", "buonasera", "barzelletta"]):
        fallback = "chat"
    elif any(kw in input_lower for kw in ["crea", "migra", "prepara", "sequenza", "completo", "nuovo servizio"]):
        fallback = "plan"
    elif any(kw in input_lower for kw in ["lista", "stato", "avvia", "ferma", "riavvia", "list", "get", "status"]):
        fallback = "act"
    elif any(kw in input_lower for kw in ["qual", "cosa", "preferenza", "ricord", "ultima volta", "storico", "tool", "strument", "accesso"]):
        fallback = "ask"
    else:
        fallback = "chat"


    logger.info(f"Rule router classified mode={fallback} for input='{user_input}'")
    return fallback
