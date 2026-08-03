import json
import logging
import threading
import time
import urllib.parse
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_client")

class MetaMCPClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: int = 15):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "LangGraph-MetaMCP-Client/1.0"
        }
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
            self.headers["x-api-key"] = self.api_key

    def _execute_sse_session(self, action_func):
        """
        Opens an SSE connection, listens for incoming JSON-RPC responses,
        initializes the MCP session, and executes action_func(send_request, wait_response).
        """
        sse_res = requests.get(self.base_url, headers={**self.headers, "Accept": "text/event-stream"}, stream=True, timeout=self.timeout)
        if sse_res.status_code != 200:
            raise RuntimeError(f"Failed to open SSE stream, status {sse_res.status_code}")

        post_url_container = []
        responses = {}
        stop_event = threading.Event()
        req_id_counter = 0
        req_lock = threading.Lock()
        post_session = requests.Session()

        def next_id():
            nonlocal req_id_counter
            with req_lock:
                req_id_counter += 1
                return req_id_counter

        def read_sse():
            try:
                for line in sse_res.iter_lines(decode_unicode=True):
                    if stop_event.is_set():
                        break
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if "sessionId=" in data_str:
                            base = urllib.parse.urlparse(self.base_url)
                            post_url = f"{base.scheme}://{base.netloc}{data_str}" if data_str.startswith("/") else data_str
                            post_url_container.append(post_url)
                        else:
                            try:
                                msg = json.loads(data_str)
                                if "id" in msg and msg["id"] is not None:
                                    responses[msg["id"]] = msg
                            except Exception:
                                pass
            except Exception:
                pass

        listener = threading.Thread(target=read_sse, daemon=True)
        listener.start()

        start = time.time()
        while not post_url_container and time.time() - start < self.timeout:
            time.sleep(0.05)

        if not post_url_container:
            stop_event.set()
            sse_res.close()
            raise RuntimeError("Timed out waiting for SSE endpoint parameter.")

        post_url = post_url_container[0]

        def send_request(method: str, params: dict = None, is_notification: bool = False):
            rid = None if is_notification else next_id()
            payload = {"jsonrpc": "2.0", "method": method}
            if rid is not None:
                payload["id"] = rid
            if params is not None:
                payload["params"] = params
            post_session.post(post_url, headers=self.headers, json=payload, timeout=self.timeout)
            return rid

        def wait_response(req_id: int, req_timeout: int = 15):
            s_time = time.time()
            while time.time() - s_time < req_timeout:
                if req_id in responses:
                    return responses[req_id]
                time.sleep(0.05)
            raise TimeoutError(f"Timeout waiting for JSON-RPC response id {req_id}")

        try:
            # 1. initialize
            init_id = send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "langgraph-agent", "version": "1.0"}
            })
            wait_response(init_id, self.timeout)
            send_request("notifications/initialized", is_notification=True)

            # 2. perform action
            return action_func(send_request, wait_response)
        finally:
            stop_event.set()
            sse_res.close()
            post_session.close()

    def list_tools(self) -> list:
        def _action(send_req, wait_resp):
            rid = send_req("tools/list", {})
            resp = wait_resp(rid, self.timeout)
            if "result" in resp and "tools" in resp["result"]:
                return resp["result"]["tools"]
            return resp.get("result", [])

        try:
            return self._execute_sse_session(_action)
        except Exception as e:
            logger.warning(f"SSE list_tools failed: {e}, attempting REST fallback")
            tools = self._list_tools_rest()
            if tools is not None:
                return tools
            raise

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        def _action(send_req, wait_resp):
            rid = send_req("tools/call", {"name": tool_name, "arguments": arguments})
            resp = wait_resp(rid, self.timeout)
            if "result" in resp:
                return resp["result"]
            if "error" in resp:
                return resp["error"]
            return resp

        try:
            return self._execute_sse_session(_action)
        except Exception as e:
            logger.warning(f"SSE call_tool failed: {e}, attempting REST fallback")
            res = self._call_tool_rest(tool_name, arguments)
            if res is not None:
                return res
            raise

    def _list_tools_rest(self):
        possible_urls = [
            self.base_url.replace("/sse", "/tools"),
            self.base_url.replace("/sse", "/openapi.json"),
        ]
        for url in possible_urls:
            try:
                res = requests.get(url, headers=self.headers, timeout=self.timeout)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "tools" in data:
                        return data["tools"]
            except Exception:
                continue
        return None

    def _call_tool_rest(self, tool_name: str, arguments: dict):
        possible_urls = [
            self.base_url.replace("/sse", f"/tools/{tool_name}/call"),
            self.base_url.replace("/sse", "/call"),
        ]
        for url in possible_urls:
            try:
                res = requests.post(url, headers=self.headers, json={"name": tool_name, "arguments": arguments}, timeout=self.timeout)
                if res.status_code == 200:
                    return res.json()
            except Exception:
                continue
        return None
