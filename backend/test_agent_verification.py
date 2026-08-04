import sys
import os
import json
import logging

# Ensure backend directory is in python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import graph
from graph import build_graph

# Set fast timeout for test execution when MetaMCP endpoint is unreachable
graph.client.timeout = 2


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_verification")

def run_test(title: str, task: str, thread_id: str, force_mode: str = None):
    print(f"\n==========================================")
    print(f"TEST: {title}")
    print(f"Task: '{task}' | Thread: '{thread_id}' | ForceMode: '{force_mode}'")
    print(f"==========================================")

    app = build_graph()
    initial_state = {
        "task": task,
        "thread_id": thread_id,
        "force_mode": force_mode,
        "agent_id": None,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": ""
    }

    config = {"configurable": {"thread_id": thread_id}}
    final_state = app.invoke(initial_state, config=config)

    mode = final_state.get("mode")
    final_response = final_state.get("final_response")
    plan = final_state.get("plan")

    print(f"[RESULT MODE]: {mode}")
    print(f"[FINAL RESPONSE]:\n{final_response}\n")

    return {
        "mode": mode,
        "response": final_response,
        "plan": plan
    }

def main():
    test_thread = "test_session_verify_1"

    # Test 1: Chat Mode
    res1 = run_test("Test 1: Ciao, chi sei?", "Ciao, chi sei?", test_thread)
    assert res1["mode"] == "chat", f"Expected mode 'chat', got '{res1['mode']}'"
    assert "memory_replace" not in res1["response"], "Found Letta internal tool in chat response!"

    # Test 2: Ask Mode (Tools query)
    res2 = run_test("Test 2: A quali tool hai accesso?", "A quali tool hai accesso?", test_thread)
    assert res2["mode"] in ["ask", "chat"], f"Expected mode 'ask' or 'chat', got '{res2['mode']}'"
    assert "Proxmox" in res2["response"] or "LXC" in res2["response"], "Response missing Proxmox/MetaMCP tools!"
    assert "memory_replace" not in res2["response"], "Found Letta internal tool in ask response!"

    # Test 3: Act Mode (Single tool execution)
    res3 = run_test("Test 3: Lista i template LXC", "Lista i template LXC", test_thread)
    assert res3["mode"] == "act", f"Expected mode 'act', got '{res3['mode']}'"
    assert res3["plan"].get("tool_name") == "proxmox-mcp__list_templates"

    # Test 4: Plan Mode (Multi-step plan)
    res4 = run_test("Test 4: Plan multi-step", "Crea un nuovo servizio web con IP libero e DNS custom", test_thread, force_mode="plan")
    assert res4["mode"] == "plan", f"Expected mode 'plan', got '{res4['mode']}'"
    assert "Crea un nuovo servizio web" in res4["response"], "Plan step does not reflect task!"

    # Test 5: Consistency test (Repeat Test 1 and 2 three times)
    print("\n--- TEST 5: Consistency Test (3 Iterations) ---")
    for i in range(1, 4):
        print(f"\n--- Iteration {i} ---")
        r_chat = run_test(f"Repeat Chat {i}", "Ciao, chi sei?", test_thread)
        assert r_chat["mode"] == "chat"
        assert "memory_replace" not in r_chat["response"]

        r_ask = run_test(f"Repeat Ask {i}", "A quali tool hai accesso?", test_thread)
        assert r_ask["mode"] in ["ask", "chat"]
        assert "memory_replace" not in r_ask["response"]

    print("\n==========================================")
    print("ALL 5 VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("==========================================")

if __name__ == "__main__":
    main()
