import logging
import httpx
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("letta_client")

LETTA_URL = config.LETTA_URL.rstrip('/')
LETTA_API_KEY = config.LETTA_API_KEY

HEADERS = {
    "Authorization": f"Bearer {LETTA_API_KEY}",
    "Content-Type": "application/json"
} if LETTA_API_KEY else {"Content-Type": "application/json"}

DEFAULT_TIMEOUT = 5.0

def _get_llm_config(client: httpx.Client):
    """Retrieves default llm_config from existing agent if available."""
    try:
        r = client.get(f"{LETTA_URL}/v1/agents/", headers=HEADERS, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            agents = r.json()
            if agents and isinstance(agents, list) and "llm_config" in agents[0]:
                return agents[0]["llm_config"]
    except Exception:
        pass
    return None

def create_thread(name: str, memory_blocks: list = None) -> str:
    """
    Creates or retrieves a Letta agent/thread by name.
    Returns agent_id (str) or None if request fails.
    """
    if not LETTA_URL or not LETTA_API_KEY:
        logger.warning("LETTA_URL or LETTA_API_KEY missing")
        return None

    with httpx.Client(follow_redirects=True) as client:
        # 1. Search existing agent by name
        for attempt in range(2):
            try:
                r = client.get(f"{LETTA_URL}/v1/agents/", headers=HEADERS, timeout=DEFAULT_TIMEOUT)
                if r.status_code == 200:
                    agents = r.json()
                    if isinstance(agents, list):
                        for ag in agents:
                            if ag.get("name") == name:
                                return ag.get("id")
                break
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} listing Letta agents failed: {e}")

        # 2. If not found, create new agent
        llm_config = _get_llm_config(client)
        payload = {"name": name}
        if llm_config:
            payload["llm_config"] = llm_config
        if memory_blocks:
            payload["memory_blocks"] = memory_blocks

        for attempt in range(2):
            try:
                r = client.post(f"{LETTA_URL}/v1/agents/", headers=HEADERS, json=payload, timeout=DEFAULT_TIMEOUT)
                if r.status_code in [200, 201]:
                    data = r.json()
                    return data.get("id")
                else:
                    logger.warning(f"Letta create_thread status {r.status_code}: {r.text[:200]}")
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} creating Letta thread failed: {e}")

    return None

def send_message(agent_id: str, role: str, content: str) -> dict:
    """
    Sends a message to a Letta agent/thread.
    Tries synchronous endpoint first, falls back to async endpoint on timeout.
    Returns response dict or None if request fails.
    """
    if not agent_id or not LETTA_URL:
        return None

    payload = {
        "messages": [
            {
                "role": role,
                "content": content
            }
        ]
    }

    with httpx.Client(follow_redirects=True) as client:
        # Try sync endpoint with timeout, then async endpoint
        for endpoint in [f"{LETTA_URL}/v1/agents/{agent_id}/messages/async", f"{LETTA_URL}/v1/agents/{agent_id}/messages"]:
            for attempt in range(2):
                try:
                    r = client.post(endpoint, headers=HEADERS, json=payload, timeout=DEFAULT_TIMEOUT)
                    if r.status_code in [200, 201]:
                        return r.json()
                    else:
                        logger.warning(f"Letta send_message ({endpoint}) status {r.status_code}: {r.text[:200]}")
                except Exception as e:
                    logger.warning(f"Attempt {attempt+1} send_message ({endpoint}) failed: {e}")

    return None

def get_messages(agent_id: str, limit: int = 50) -> list:
    """
    Retrieves message history from Letta agent/thread.
    Returns list of messages or None if request fails.
    """
    if not agent_id or not LETTA_URL:
        return None

    with httpx.Client(follow_redirects=True) as client:
        for attempt in range(2):
            try:
                r = client.get(f"{LETTA_URL}/v1/agents/{agent_id}/messages?limit={limit}", headers=HEADERS, timeout=DEFAULT_TIMEOUT)
                if r.status_code == 200:
                    return r.json()
                else:
                    logger.warning(f"Letta get_messages status {r.status_code}: {r.text[:200]}")
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} get_messages failed: {e}")

    return None

def filter_clean_messages(messages: list) -> list:
    """
    Filters raw Letta messages to return only clean user and main-agent conversation turns,
    excluding Letta internal agent responses, reasoning, and system messages.
    """
    if not messages or not isinstance(messages, list):
        return []

    clean_msgs = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        
        m_type = str(msg.get("message_type") or msg.get("role") or "").lower()
        if "system" in m_type or "reasoning" in m_type or "tool" in m_type:
            continue
            
        # Ignore assistant messages generated internally by Letta's agent
        if m_type == "assistant_message" or m_type == "assistant":
            continue

        if m_type == "user_message" or m_type == "user":
            txt = msg.get("text") or msg.get("content") or msg.get("message") or ""
            if not txt:
                continue
                
            msg_id = msg.get("id") or "msg"
            date_val = msg.get("date") or msg.get("created_at")
            
            # Check if this user_message was committed as "User: ... \nAssistant: ..."
            if "User: " in txt and "Assistant: " in txt:
                parts = txt.split("Assistant: ", 1)
                user_part = parts[0].replace("User: ", "").strip()
                ast_part = parts[1].strip() if len(parts) > 1 else ""
                
                if user_part:
                    clean_msgs.append({
                        "id": f"{msg_id}_u",
                        "date": date_val,
                        "message_type": "user_message",
                        "content": user_part
                    })
                if ast_part:
                    clean_msgs.append({
                        "id": f"{msg_id}_a",
                        "date": date_val,
                        "message_type": "assistant_message",
                        "content": ast_part
                    })
            else:
                clean_msgs.append({
                    "id": msg_id,
                    "date": date_val,
                    "message_type": "user_message",
                    "content": txt
                })

    return clean_msgs

def delete_thread(agent_id: str) -> bool:
    """Deletes a Letta agent/thread by agent_id."""
    if not agent_id or not LETTA_URL:
        return False
    try:
        with httpx.Client(follow_redirects=True) as client:
            r = client.delete(f"{LETTA_URL}/v1/agents/{agent_id}", headers=HEADERS, timeout=DEFAULT_TIMEOUT)
            return r.status_code in [200, 204]
    except Exception as e:
        logger.warning(f"Failed to delete Letta thread {agent_id}: {e}")
        return False


