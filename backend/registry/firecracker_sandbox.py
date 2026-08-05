import os
import time
import json
import base64
import uuid
import logging
import requests
import subprocess
from typing import Dict, Any

from mcp_client import MetaMCPClient
import config

logger = logging.getLogger("firecracker_sandbox")

class FirecrackerSandbox:
    def __init__(self):
        self.api_url = config.FIRECRACKER_API_URL
        self.kernel_path = config.FIRECRACKER_KERNEL_PATH
        self.rootfs_path = config.FIRECRACKER_ROOTFS_PATH
        self.mcp = MetaMCPClient(config.METAMCP_URL, api_key=config.METAMCP_API_KEY)

    def is_available(self) -> bool:
        """Verifica se l'API HTTP di Firecracker è raggiungibile."""
        try:
            res = requests.get(f"{self.api_url}/machine-config", timeout=2)
            return res.status_code == 200
        except requests.RequestException:
            return False

    def execute_code(self, code: str, timeout: int = 10) -> Dict[str, Any]:
        """
        Esegue codice Python in una microVM Firecracker reale col Guest Runner.
        Se l'infrastruttura o l'API falliscono, ricorre al fallback locale con sandboxed=False.
        """
        if not self.is_available():
            logger.warning(f"API Firecracker non disponibile su {self.api_url}. Uso fallback.")
            return self._execute_fallback(code, timeout=timeout)

        run_id = str(uuid.uuid4())[:8]
        payload_file_host = f"/tmp/fc_payload_{run_id}.raw"

        try:
            # 1. Prepariamo il payload block device (/dev/vdb) sull'host
            b64_code = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            payload_content = f"<<<PAYLOAD_START>>>{b64_code}<<<PAYLOAD_END>>>\n"
            
            b64_payload_file = base64.b64encode(payload_content.encode("utf-8")).decode("utf-8")
            create_cmd = (
                f"truncate -s 1M {payload_file_host} && "
                f"echo '{b64_payload_file}' | base64 -d | dd of={payload_file_host} conv=notrunc"
            )
            self.mcp.call_tool("exec_host_command", {"command": create_cmd})

            # 2. Configurazione VM via API REST
            boot_args = "console=ttyS0 quiet panic=1 pci=off init=/usr/local/bin/guest_runner.sh"
            
            res_boot = requests.put(f"{self.api_url}/boot-source", json={
                "kernel_image_path": self.kernel_path,
                "boot_args": boot_args
            }, timeout=3)
            res_boot.raise_for_status()

            res_root = requests.put(f"{self.api_url}/drives/rootfs", json={
                "drive_id": "rootfs",
                "path_on_host": self.rootfs_path,
                "is_root_device": True,
                "is_read_only": True
            }, timeout=3)
            res_root.raise_for_status()

            res_vdb = requests.put(f"{self.api_url}/drives/payload", json={
                "drive_id": "payload",
                "path_on_host": payload_file_host,
                "is_root_device": False,
                "is_read_only": False
            }, timeout=3)
            res_vdb.raise_for_status()

            # Avvio MicroVM
            res_start = requests.put(f"{self.api_url}/actions", json={
                "action_type": "InstanceStart"
            }, timeout=3)
            res_start.raise_for_status()

            # 3. Attesa risultato leggendo il payload block device
            start_time = time.time()
            res_data = None
            
            while time.time() - start_time < timeout:
                time.sleep(0.3)
                read_res = self.mcp.call_tool("exec_host_command", {
                    "command": f"cat {payload_file_host} | tr -d '\\000'"
                })
                if read_res and isinstance(read_res, dict) and "stdout" in read_res:
                    out = read_res["stdout"]
                    if "<<<RESULT_START>>>" in out and "<<<RESULT_END>>>" in out:
                        s_idx = out.find("<<<RESULT_START>>>") + len("<<<RESULT_START>>>")
                        e_idx = out.find("<<<RESULT_END>>>")
                        b64_json = out[s_idx:e_idx].strip()
                        res_json_str = base64.b64decode(b64_json).decode("utf-8")
                        res_data = json.loads(res_json_str)
                        break

            if not res_data:
                logger.warning("Timeout risposta microVM Firecracker. Uso fallback.")
                return self._execute_fallback(code, timeout=timeout)

            return {
                "output": res_data.get("output", ""),
                "success": res_data.get("success", False),
                "sandboxed": True,
                "error": res_data.get("error")
            }

        except Exception as e:
            logger.warning(f"Errore esecuzione Firecracker: {e}. Uso fallback.")
            return self._execute_fallback(code, timeout=timeout)
        finally:
            # Cleanup file temporaneo sull'host
            try:
                self.mcp.call_tool("exec_host_command", {"command": f"rm -f {payload_file_host}"})
            except Exception:
                pass

    def _execute_fallback(self, code: str, timeout: int = 5) -> Dict[str, Any]:
        """Fallback temporaneo via subprocess locale sul CT backend."""
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
                return {"output": stdout, "success": True, "sandboxed": False, "error": None}
            else:
                return {"output": stdout, "success": False, "sandboxed": False, "error": stderr or f"Exit code {res.returncode}"}
        except subprocess.TimeoutExpired:
            return {"output": "", "success": False, "sandboxed": False, "error": f"Timeout esecuzione ({timeout}s) superato."}
        except Exception as e:
            return {"output": "", "success": False, "sandboxed": False, "error": str(e)}
