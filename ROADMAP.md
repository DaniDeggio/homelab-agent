# Homelab Agent — Report & Roadmap (2026-08-22)

## 1. Stato attuale

### Backend (`homelab-agent/backend`)
- **Stack**: FastAPI + LangGraph (StateGraph con `SqliteSaver`), loop ReAct custom, client MetaMCP custom (SSE + JSON-RPC, fallback REST), memoria ibrida (Letta remoto + JSONL locale + SQLite), LLM via llama.cpp OpenAI-compatible.
- **Endpoint**: `/v1/health`, `/v1/chat|ask|act|plan|invoke`, `/v1/invoke_stream` (SSE), CRUD `/v1/threads`.
- **Mode routing**: `router.py` classifica input in chat/ask/act/plan (regole + fallback LLM); `mode_policy.py` definisce budget tool/reasoning per mode.
- **Tool calling**: catalogo dinamico da MetaMCP (cache 5 min), selezione schema-guidata (`ToolSelection`), registries: metamcp / web / code.
- **Test**: 6 suite presenti (tool selection, modes, phase4, rollback, verification, conversation length).

### Frontend (`homelab-agent/frontend`)
- React/Vite/TS. Thread list, streaming SSE live (reasoning + content), ReasoningBlock, PlanViewer, ExecutionTraceViewer, ToolLog, MarkdownRenderer (react-markdown + remark-gfm).
- **Mancanze**: no syntax highlighting, no WebSocket, nessuna gestione multi-user/auth UI.

### ProxmoxMcp
- Config Pydantic solida, provisioning con step tracking + rollback parziale, IPAM su file JSON con lock, test coverage buona.
- **Criticità**: default di rete hardcoded (192.168.1.x, vmbr0, homelab.local), bootstrap all-or-nothing senza degrado graceful.

## 2. Gap principali vs reference (open-webui, odysseus)

| Area | Stato homelab-agent | Reference pattern |
|---|---|---|
| Provider LLM | Solo llama.cpp via `requests.post` | Adapter multi-provider (OpenAI/Ollama/local) normalizzati |
| Auth | API key opzionale, CORS `*`, single-user | JWT/OAuth, RBAC, multi-user, sessioni |
| Streaming | SSE custom via queue+thread | SSE/Socket.IO strutturato con eventi tipizzati |
| Memory/RAG | Letta + JSONL, `sqlite-vec` installato ma non usato, hybrid retrieval non collegato al grafo | Memory manager + KB/RAG first-class come tool |
| Tool system | Solo MetaMCP + web + code | Tool registry con access control, MCP stdio/SSE/HTTP, permission read/write |
| Persistenza | SQLite checkpoints + JSONL | DB ORM modulare, file storage, Redis per stato live |
| Osservabilità | execution trace in UI | audit log persistente, metriche, health dei provider |
| Robustezza | bootstrap fragile, nessun health-check provider esterni | fallback, retry, circuit breaker |

## 3. Piano — Fase 0: Hardening (priorità alta) ✅ IMPLEMENTATA
1. ✅ **Auth obbligatoria**: fail-fast al boot se `API_SECRET_KEY` manca (bypass con `ALLOW_INSECURE=1`). CORS ristretto a `CORS_ORIGINS` da `.env`.
2. ✅ **Rate limiting** con slowapi (`RATE_LIMIT`, default 30/min) su chat/ask/act/plan/invoke/invoke_stream.
3. ✅ **Guardrail host-level**: `guardrails.py` classifica i tool (safe/write/risky), blocca comandi shell pericolosi (rm -rf /, mkfs, dd, fork bomb...) e richiede `"confirm": true` per tool rischiosi.
4. ✅ **Audit log persistente**: tabella `audit_log` in SQLite + endpoint `GET /v1/audit`; ogni tool call registra thread, mode, args, risultato, durata.
5. ✅ **Config**: `config.py` migrato a Pydantic Settings; tutte le costanti mantenute per retrocompatibilità.

> Nota: il guardrail "confirm" è lato agent — l'LLM deve includere `confirm: true`. Il gate di conferma utente via UI è previsto in Fase 3.2/4.2.

## 4. Piano — Fase 1: Architettura backend (1.1–1.4 ✅, 1.5 differita)
1. ✅ **Provider abstraction**: `providers.py` con `OpenAICompatProvider` (llama.cpp/vLLM/LM Studio) e `OllamaProvider`; `_call_llm` delega al provider; estrazione `<think>` unificata; supporto `OLLAMA_URL` opzionale in config.
2. ✅ **SDK MCP ufficiale**: `mcp_sdk_client.py` (ClientSession + sse_client, sessione persistente, retry con reset); `MetaMCPRegistry` usa l'SDK con fallback automatico al client legacy.
3. ⏳ **Refactor streaming async**: differito — la coda+thread attuale funziona; eventi già tipizzati (`reasoning|content|final|error`). Da migrare ad async generator in Fase 4 insieme al frontend.
4. ✅ **Health checks**: `GET /v1/status` pinga in parallelo llama.cpp, MetaMCP e Letta + health dei provider; ritorna `ok`/`degraded`.
5. ⏳ **Struttura a pacchetti**: differita per non rompere i deployment esistenti (CT 112); da fare in una release dedicata con aggiornamento systemd.

## 5. Piano — Fase 2: Memory & RAG
1. Attivare davvero `sqlite-vec`: embedding store per fatti salienti e summary thread; retrieval nel nodo `retrieve_memory`.
2. Collegare `search_archival_memory_hybrid` (Letta) al grafo come tool/recall automatico.
3. Knowledge base documenti (pattern odysseus `rag_server`): upload PDF/md, chunking, embedding, ricerca come tool `knowledge_search`.
4. Compattazione conversazione: riassunto automatico quando la cronologia supera una soglia token.

## 6. Piano — Fase 3: Tool system evoluto
1. Tool registry unificato con metadata: categoria, read-only vs write, rischio, registry di origine.
2. Permission model per mode già esistente → estendere con **approval workflow**: tool "write/risky" richiedono conferma UI prima dell'esecuzione.
3. Parallel tool calls dove sicuro (solo read-only).
4. Cache e deduplicazione risultati tool identici nello stesso run.

## 7. Piano — Fase 4: Frontend
1. Syntax highlighting codice (rehype-highlight/Shiki) nel MarkdownRenderer.
2. Pannello approvazione tool (collegato a Fase 3.2).
3. Visualizzazione memoria (fatti salienti, summary per thread).
4. Upload documenti per la KB (Fase 2.3).
5. Impostazioni runtime: selezione modello/provider, budget reasoning già presente → aggiungere temperature, max tokens.

## 8. Piano — Fase 5: Qualità & ops
1. CI: lint (ruff, mypy) + pytest backend + tsc/vitest frontend.
2. Test integrazione con MetaMCP mockato; test E2E streaming.
3. Docker compose per dev locale (backend+frontend+mock MCP).
4. Documentazione: aggiornare README backend con architettura e sequenze (mermaid).

## 9. Ordine di esecuzione consigliato
Fase 0 → 1 → 2 → 3 → 4 → 5. Fasi 0–1 sbloccano sicurezza e manutenibilità; 2–3 sono il valore aggiunto da agente; 4–5 consolidano UX e qualità.
