# Homelab Agent (`homelab-agent`)

Agente AI autonomo per la gestione dell'infrastruttura Proxmox VE con orchestrazione MetaMCP, supporto LangGraph, memoria conversazionale ibrida, selezione dinamica dei tool e motore di rollback transazionale automatico.

---

## 🔄 Rollback Automatico Transazionale & Declarative Undo Engine (Fase 3)

Sostituito il vecchio sistema di rollback hardcoded con un motore generale e transazionale basato sul pattern **Saga** e **Write-Ahead Logging (WAL)**:

- **Declarative Rollback Schema (`tool_catalog.py`)**:
  - Ogni tool dichiara la sua azione di compensazione inversa (es. `allocate_ip` ➔ `release_ip`, `create_lxc_from_template` ➔ `stop_container`, `add_pihole_dns_record` ➔ `delete_pihole_dns_record`, `create_npm_proxy_host` ➔ `delete_npm_proxy_host`).
  - Mappa i template degli argomenti (`rollback_args_template`) con i risultati di esecuzione effettivi (`{{vmid}}`, `{{ip}}`, `{{domain}}`).
- **Transaction Log & LIFO Undo Stack (`ExecutionLog` in `graph.py`)**:
  - Ogni step viene registrato su un registro transazionale *prima* dell'esecuzione (WAL pattern).
  - In caso di fallimento durante l'esecuzione di un piano, il sistema scorre il registro in ordine inverso (LIFO Undo Stack), eseguendo il rollback **esclusivamente per gli step completati con successo**.
- **Skipping dei Tool Non Reversibili**:
  - I tool non reversibili (es. `exec_lxc_command`, `list_containers`) vengono identificati e ignorati in sicurezza durante il rollback con warning nei log.
- **LLM-Based Rollback Planning (Fallback)**:
  - Se il rollback dichiarativo per alcuni step fallisce o se vi sono operazioni non reversibili, l'LLM genera un piano di rollback manuale contestuale basato sullo stato dell'infrastruttura.

---

## 🛠️ Selezione Dinamica dei Tool via LLM (Fase 2)

- **Catalogo Dinamico con Cache TTL 5m (`tool_catalog.py`)**: Recupera la lista dei tool dal protocollo SSE/MCP o OpenAPI.
- **Structured Output & Schema Validation (`tool_schemas.py`)**: Modello Pydantic `ToolSelection` con validazione `jsonschema`.
- **Loop di Self-Correction (`act_graph_node`)**: Iniezione degli errori di validazione per la ri-generazione guidata (fino a 2 retries).

---

## 🧠 Architettura della Memoria Conversazionale Ibrida (Fase 1)

- **Tier 1 — In-Context Memory**: Sliding window degli ultimi 20 messaggi + summary incrementale via LLM per conversazioni lunghe (>30 messaggi).
- **Tier 2 — Session-Scoped Archival Memory**: Integrazione con Letta.
- **Tier 3 — Cross-Session Persistence**: Log append-only JSONL (`memory/{thread_id}.jsonl`).

---

## ⚙️ Modalità Operative (Grafo LangGraph)
1. **CHAT**: Conversazione naturale con memoria storica sliding window + summary.
2. **ASK**: Consultazione del catalogo tool (34 tool MetaMCP) e interrogazioni sulla memoria.
3. **ACT**: Esecuzione dinamica di tool MetaMCP Proxmox guidata da LLM Structured Output con self-correction.
4. **PLAN**: Generazione di piani multi-step JSON strutturati (`plan_structure`) con ordinamento topologico (`depends_on`), estrazione ricorsiva delle variabili ed esecuzione transazionale con **rollback automatico dichiarativo e LIFO undo stack**.
