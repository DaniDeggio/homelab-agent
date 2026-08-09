import re

# Regex to match <think> or <thought> blocks (including attributes like <think time="0.4">)
# It uses DOTALL to match across newlines, and it handles both closed and unclosed tags.
_THINK_OPEN_TAG_RE = re.compile(r'<(?:think|thought|thinking)(?:\s+[^>]*)?>', flags=re.IGNORECASE)
_THINK_CLOSE_TAG_RE = re.compile(r'</(?:think|thought|thinking)>', flags=re.IGNORECASE)

# Catch-all for a complete block (non-greedy)
_THINK_BLOCK_RE = re.compile(r'<(?:think|thought|thinking)[^>]*>.*?</(?:think|thought|thinking)>', flags=re.IGNORECASE | re.DOTALL)

# Catch-all for unclosed block at the start or anywhere
_THINK_UNCLOSED_RE = re.compile(r'<(?:think|thought|thinking)[^>]*>.*', flags=re.IGNORECASE | re.DOTALL)

def strip_thinking(text: str) -> str:
    """
    Rimuove in modo robusto i blocchi di reasoning (es. <think>...</think>)
    generati dai modelli LLM. 
    Questa operazione previene la rottura del parser JSON se il modello
    decide di pensare ad alta voce prima di restituire l'output strutturato.
    """
    if not text:
        return ""
    
    # 1. Rimuovi i blocchi correttamente chiusi
    out = _THINK_BLOCK_RE.sub("", text)
    
    # 2. Se c'è un tag di apertura ma non di chiusura (es. modello interrotto o streaming in blocco)
    # Togliamo tutto ciò che va dal tag di apertura in poi (pericoloso se l'output utile è dopo,
    # ma di solito il JSON è *dopo* il blocco di think. Se il think non è chiuso, il JSON non c'è).
    # Per sicurezza, togliamo solo il tag se il JSON è dopo.
    # Invece di usare _THINK_UNCLOSED_RE, facciamo un replace sui tag orfani:
    out = _THINK_OPEN_TAG_RE.sub("", out)
    out = _THINK_CLOSE_TAG_RE.sub("", out)
    
    return out.strip()
