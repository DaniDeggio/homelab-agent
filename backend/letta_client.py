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
