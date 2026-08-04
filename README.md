# Homelab Agent (`homelab-agent`)

Agente AI autonomo per la gestione dell'infrastruttura Proxmox VE con orchestrazione MetaMCP, supporto LangGraph e memoria conversazionale ibrida.

---

## 🧠 Architettura della Memoria Conversazionale Ibrida (Fase 1)

L'agente implementa un sistema di memoria multi-livello a tre livelli per garantire prestazioni costanti (<2s per messaggio) anche su conversazioni di 50+ interazioni senza saturazione del contesto:

### Tier 1 — In-Context Memory (Sliding Window + Incremental Summary)
- **Messaggi recenti (Sliding Window)**: Mantiene gli ultimi 20 messaggi grezzi (`User` + `Assistant`) per garantire massima aderenza al contesto immediato.
- **Riepilogo incrementale (Summary)**: Quando la conversazione supera i 30 messaggi, gli step precedenti vengono sintetizzati in un riassunto compatto di massimo 5 frasi generato via LLM (`_generate_summary`).
- **Dimensione contesto**: Bounded a ~2000 token totali.

### Tier 2 — Session-Scoped Archival Memory (Letta)
- Salvataggio vettoriale e archivistico dei fatti salienti e dei riassunti delle sessioni via `save_archival_memory` e `get_archival_memory`.

### Tier 3 — Cross-Session Append-Only File System Persistence
- Ogni turno di conversazione (messaggi utente e risposte assistente) viene salvato su file di log locale in formato JSONL (`memory/{thread_id}.jsonl`).
- Permette il recovery istantaneo e l'audit completo anche in caso di disconnessione o riavvio del servizio.

---

## 🛠️ Modalità Operative (Grafo LangGraph)
1. **CHAT**: Conversazione naturale con memoria storica sliding window + summary.
2. **ASK**: Consultazione del catalogo tool (34 tool MetaMCP) e interrogazioni sulla memoria.
3. **ACT**: Esecuzione singola di tool MetaMCP Proxmox.
4. **PLAN**: Generazione di piani multi-step JSON strutturati (`plan_structure`) con ordinamento topologico (`depends_on`), estrazione ricorsiva delle variabili (`extract_output_var`) ed esecuzione con rollback parziale automatico.
