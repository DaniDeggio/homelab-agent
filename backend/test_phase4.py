import json
import logging
from pathlib import Path

from analyze_monitoring import analyze_monitoring_logs
from graph import AgentSpan, extract_salient_facts
from letta_client import BM25Retriever, reciprocal_rank_fusion

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_phase4")

def test_phase4_optimizations():
    print("==========================================")
    print("TEST: Phase 4 Advanced Optimizations")
    print("==========================================")

    # 1. Test BM25 Retriever & RRF Fusion
    docs = [
        "Container LXC 100 con Debian 12 ed 8GB di RAM",
        "Assegnato indirizzo IP statico 192.168.1.180 da IPAM",
        "Configurato record DNS test-service.home.lab su Pi-hole",
        "Host proxy configurato su Nginx Proxy Manager per porta 8080"
    ]

    bm25 = BM25Retriever()
    bm25.index(docs)

    # BM25 exact match search for IP address
    results = bm25.search("192.168.1.180", k=2)
    assert len(results) > 0
    top_doc_idx = results[0][0]
    assert "192.168.1.180" in docs[top_doc_idx]
    print(f"✅ BM25 exact match search succeeded for '192.168.1.180' -> Doc {top_doc_idx}: '{docs[top_doc_idx]}'")

    # RRF Fusion test
    bm25_ranks = [(1, 4.5), (0, 2.1), (2, 1.0)]
    dense_ranks = [(0, 0.95), (1, 0.80), (3, 0.60)]
    fused = reciprocal_rank_fusion([bm25_ranks, dense_ranks], k=60, top_n=3)
    assert len(fused) == 3
    print("✅ Reciprocal Rank Fusion (RRF) test succeeded:", fused)

    # 2. Test Monitoring & Metric Aggregation
    test_log_file = Path(__file__).parent / "memory" / "test_monitoring_logs.jsonl"
    if test_log_file.exists():
        test_log_file.unlink()

    span1 = AgentSpan("sess_1", "thread_1", "Lista container", llm_latency_ms=150.0, prompt_tokens=100, completion_tokens=50)
    span2 = AgentSpan("sess_2", "thread_1", "Allocazione IP", llm_latency_ms=300.0, prompt_tokens=200, completion_tokens=80)
    span3 = AgentSpan("sess_3", "thread_2", "Creazione LXC", llm_latency_ms=500.0, prompt_tokens=250, completion_tokens=120)

    for span in [span1, span2, span3]:
        with open(test_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(span.to_dict()) + "\n")

    metrics = analyze_monitoring_logs(str(test_log_file))
    print("Aggregated Metrics:\n", json.dumps(metrics, indent=2))
    assert metrics["status"] == "ok"
    assert metrics["total_sessions"] == 3
    assert metrics["latency_p50_ms"] >= 150.0
    assert metrics["total_tokens"] == (100+50 + 200+80 + 250+120)
    print("✅ Monitoring log parsing and P50/P90/P99 latency aggregation succeeded!")

    # Clean up test log file
    if test_log_file.exists():
        test_log_file.unlink()

    # 3. Test Salient Fact Extraction
    task = "Preferisco sempre usare distribuzioni Linux Debian per tutti i container LXC del mio Homelab."
    response = "Ricevuto! Userò sempre Debian come distribuzione predefinita per i nuovi container LXC."
    facts = extract_salient_facts(task, response, "")
    print("Extracted Salient Facts:\n", facts)
    assert len(facts) > 0
    print("✅ Salient Fact Extraction succeeded!")

    print("\n==========================================")
    print("ALL PHASE 4 OPTIMIZATION TESTS PASSED SUCCESSFULLY!")
    print("==========================================")

if __name__ == "__main__":
    test_phase4_optimizations()
