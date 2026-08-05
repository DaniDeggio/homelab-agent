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
        # MetaMCP client per interagire con l'host Proxmox per il recupero output
        self.mcp = MetaMCPClient(config.METAMCP_URL, api_key=config.METAMCP_API_KEY)

    def is_available(self) -> bool:
        """Verifica se l'API HTTP di Firecracker è raggiungibile."""
        try:
            res = requests.get(f"{self.api_url}", timeout=2)
            # Anche se restituisce 404 per root path, significa che il server risponde
            return True
        except requests.RequestException:
            return False

    def execute_code(self, code: str, timeout: int = 5) -> Dict[str, Any]:
        """
        Esegue codice Python in microVM effimera tramite API HTTP di Firecracker.
        Se Firecracker non è raggiungibile, degrada a subprocess locale con sandboxed=False.
        """
        if not self.is_available():
            logger.warning(f"API Firecracker ({self.api_url}) non raggiungibile. Uso fallback.")
            return self._execute_fallback(code, timeout=timeout)

        run_id = str(uuid.uuid4())[:8]
        output_file_host = f"/tmp/fc_out_{run_id}.raw"
        
        try:
            # 1. Prepariamo un block device RAW sull'host per catturare l'output
            # Usiamo MCP per creare il file vuoto sull'host (1MB)
            create_cmd = f"truncate -s 1M {output_file_host}"
            self.mcp.call_tool("exec_host_command", {"command": create_cmd})

            # 2. Prepariamo lo script codificato in base64 per evitare problemi di escaping
            b64_code = base64.b64encode(code.encode('utf-8')).decode('utf-8')
            
            # 3. Boot args: decodifica, esegue, scrive su /dev/vdb (il nostro file raw) e spegne
            # Aggiungiamo un marker EOF per capire quando ha finito
            eof_marker = f"---EOF-{run_id}---"
            sh_cmd = f"python3 -c \"import base64; exec(base64.b64decode(b'{b64_code}').decode('utf-8'))\" > /dev/vdb 2>&1; echo '\n{eof_marker}' >> /dev/vdb; poweroff -f"
            boot_args = f"console=ttyS0 quiet panic=1 pci=off init=/bin/sh -c \"{sh_cmd}\""

            # 4. Configurazione VM via API REST
            # Imposta kernel
            res_boot = requests.put(f"{self.api_url}/boot-source", json={
                "kernel_image_path": self.kernel_path,
                "boot_args": boot_args
            }, timeout=3)
            res_boot.raise_for_status()

            # Imposta rootfs (vda)
            res_rootfs = requests.put(f"{self.api_url}/drives/rootfs", json={
                "drive_id": "rootfs",
                "path_on_host": self.rootfs_path,
                "is_root_device": True,
                "is_read_only": True
            }, timeout=3)
            res_rootfs.raise_for_status()

            # Imposta drive di output (vdb)
            res_outdrive = requests.put(f"{self.api_url}/drives/output", json={
                "drive_id": "output",
                "path_on_host": output_file_host,
                "is_root_device": False,
                "is_read_only": False
            }, timeout=3)
            res_outdrive.raise_for_status()

            # 5. Avvia la microVM
            res_start = requests.put(f"{self.api_url}/actions", json={
                "action_type": "InstanceStart"
            }, timeout=3)
            res_start.raise_for_status()

            # 6. Attendi il completamento leggendo ciclicamente l'output via host
            start_time = time.time()
            output_content = ""
            success = False

            while time.time() - start_time < timeout:
                time.sleep(0.5)
                # Leggi il file raw dall'host
                cat_res = self.mcp.call_tool("exec_host_command", {"command": f"cat {output_file_host} | tr -d '\\000'"})
                
                if cat_res and isinstance(cat_res, dict) and "stdout" in cat_res:
                    curr_out = cat_res["stdout"]
                    if eof_marker in curr_out:
                        output_content = curr_out.split(eof_marker)[0].strip()
                        success = True
                        break

            if not success:
                return {"output": "Timeout o fallimento microVM", "success": False, "sandboxed": True, "error": f"Timeout {timeout}s superato"}

            return {"output": output_content, "success": True, "sandboxed": True, "error": None}

        except Exception as e:
            logger.warning(f"Errore durante l'esecuzione in Firecracker: {e}. Uso fallback.")
            return self._execute_fallback(code, timeout=timeout)
        finally:
            # 7. Pulizia file di output sull'host
            try:
                self.mcp.call_tool("exec_host_command", {"command": f"rm -f {output_file_host}"})
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

