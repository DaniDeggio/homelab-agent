import os
from pathlib import Path

def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

load_env()

METAMCP_URL = os.getenv("METAMCP_URL", "http://192.168.1.175:12008/metamcp/MetaMCP/sse")
METAMCP_URL_HTTP = os.getenv("METAMCP_URL_HTTP", "http://192.168.1.175:12008")
METAMCP_API_KEY = os.getenv("METAMCP_API_KEY", "")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "Qwen3.6-35B-HugeCtx")
LLAMA_CPP_URL = os.getenv("LLAMA_CPP_URL", "http://192.168.1.159:8080/v1")
LETTA_URL = os.getenv("LETTA_URL", "http://192.168.1.177:8083")
LETTA_API_KEY = os.getenv("LETTA_API_KEY", "")
CHECKPOINT_DB_PATH = os.getenv("CHECKPOINT_DB_PATH", str(Path(__file__).parent / "checkpoints.db"))
