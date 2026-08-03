# Home Lab Agent - Backend

Backend LangGraph + FastAPI per l'agente AI del mio homelab.

## Struttura

- `main.py`: CLI entry point
- `graph.py`: grafo LangGraph (intake → retrieve_memory → mode_router → chat/ask/act/plan → commit_memory → respond)
- `letta_client.py`: client HTTP per Letta (memoria conversazionale)
- `mcp_client.py`: client SSE/HTTP per MetaMCP (tool Proxmox)
- `router.py`: mode router neurale (chat/ask/act/plan)
- `config.py`: parser .env
- `api.py`: API REST FastAPI
- `schemas.py`: modelli Pydantic
- `run_api.py`: entry point uvicorn

## Installazione

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configurazione

Copia `.env.example` in `.env` e compila:
```
METAMCP_URL=http://192.168.1.175:12008/metamcp/MetaMCP/sse
METAMCP_API_KEY=<tua_api_key>
LLAMA_CPP_URL=http://192.168.1.159:8080/v1
DEFAULT_MODEL=qwen-3.6-35b-hugectx
LETTA_URL=http://192.168.1.177:8083
LETTA_API_KEY=<tua_api_key>
CHECKPOINT_DB_PATH=/opt/main-agent/checkpoints.db
API_SECRET_KEY=<opzionale, per auth API>
```

## Avvio

### CLI
```bash
.venv/bin/python3 main.py "task" --thread alice
```

### API REST
```bash
.venv/bin/python3 run_api.py
```

### Systemd (produzione)
```bash
sudo systemctl start main-agent-api
sudo systemctl enable main-agent-api
```

## Test

```bash
curl http://localhost:8090/v1/health
curl -X POST http://localhost:8090/v1/chat -H "Content-Type: application/json" -d '{"input": "Ciao", "thread_id": "test"}'
```
