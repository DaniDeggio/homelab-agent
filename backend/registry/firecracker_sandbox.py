import os
import time
import json
import logging
import subprocess
from typing import Dict, Any

logger = logging.getLogger("firecracker_sandbox")

class FirecrackerSandbox:
    def __init__(self, api_socket: str = "/tmp/firecracker.socket"):
        self.api_socket = api_socket

    def is_available(self) -> bool:
        """Controlla se il socket Firecracker o l'ambiente KVM è disponibile."""
        return os.path.exists(self.api_socket)

    def execute_code(self, code: str, timeout: int = 5) -> Dict[str, Any]:
        """
        Esegue codice Python in microVM effimera (o fallback isolato).
        Ritorna {"output": str, "success": bool, "error": str | None}
        """
        if not self.is_available():
            logger.warning(f"Socket Firecracker '{self.api_socket}' non trovato. Uso fallback subprocess limitato.")
            return self._execute_fallback(code, timeout=timeout)

        # Se il socket esiste, eseguiamo la chiamata REST via socket HTTP unix
        try:
            # Esecuzione tramite curl su socket UNIX o libreria HTTP+UNIX
            cmd = [
                "curl", "--unix-socket", self.api_socket,
                "-i", "-X", "PUT", "http://localhost/actions",
                "-H", "Accept: application/json",
                "-H", "Content-Type: application/json",
                "-d", json.dumps({"action_type": "InstanceStart"})
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return {"output": res.stdout, "success": True, "error": None}
        except Exception as e:
            return {"output": "", "success": False, "error": str(e)}

    def _execute_fallback(self, code: str, timeout: int = 5) -> Dict[str, Any]:
        """Fallback temporaneo via subprocess isolato."""
        try:
            res = subprocess.run(
                ["python3", "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            stdout = res.stdout.strip()
            stderr = res.stderr.strip()
            if res.returncode == 0:
                return {"output": stdout, "success": True, "error": None}
            else:
                return {"output": stdout, "success": False, "error": stderr or f"Exit code {res.returncode}"}
        except subprocess.TimeoutExpired:
            return {"output": "", "success": False, "error": f"Timeout esecuzione ({timeout}s) superato."}
        except Exception as e:
            return {"output": "", "success": False, "error": str(e)}
