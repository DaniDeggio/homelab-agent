import time
import logging
from unittest.mock import patch, MagicMock
from graph import build_graph, ExecutionLog, execute_rollback_for_step, generate_rollback_plan_with_llm
from tool_catalog import get_tool_catalog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_rollback")

def test_rollback_engine():
    print("==========================================")
    print("TEST: Declarative & Transactional Rollback Engine (Phase 3)")
    print("==========================================")

    app = build_graph()
    test_thread = f"test_rollback_{int(time.time())}"
    tools_catalog = get_tool_catalog()

    # 1. Test Declarative Rollback on Plan Failure
    plan_struct = {
        "steps": [
            {
                "id": 1,
                "tool": "proxmox-mcp__allocate_ip",
                "args": {"vmid": 200, "hostname": "test-rollback"},
                "output_var": "allocated_ip",
                "description": "Allocazione IP statico"
            },
            {
                "id": 2,
                "tool": "proxmox-mcp__create_lxc_from_template",
                "args": {"template_vmid": 100, "name": "test-rollback"},
                "output_var": "vmid",
                "depends_on": 1,
                "description": "Creazione container LXC"
            },
            {
                "id": 3,
                "tool": "proxmox-mcp__add_pihole_dns_record",
                "args": {"domain": "test-rollback.lab", "target_ip": "{{allocated_ip}}"},
                "depends_on": 2,
                "description": "Configurazione DNS Pi-hole"
            }
        ]
    }

    called_rollback_tools = []

    def mock_call_tool(tool_name, arguments):
        if tool_name == "proxmox-mcp__allocate_ip":
            return {"ip": "192.168.1.250", "status": "allocated"}
        elif tool_name == "proxmox-mcp__create_lxc_from_template":
            return {"vmid": 250, "status": "created"}
        elif tool_name == "proxmox-mcp__add_pihole_dns_record":
            return {"error": "Simulated Pi-hole API Timeout"}
        else:
            called_rollback_tools.append((tool_name, arguments))
            return {"status": "success"}

    with patch("graph.client.call_tool", side_effect=mock_call_tool):
        initial_state = {
            "task": "Test Rollback Execution",
            "thread_id": test_thread,
            "force_mode": "act",
            "execute": True,
            "plan_structure": plan_struct,
            "agent_id": None,
            "memory_context": None,
            "mode": "",
            "plan": {},
            "tool_result": None,
            "final_response": ""
        }
        config = {"configurable": {"thread_id": test_thread}}
        final_state = app.invoke(initial_state, config=config)

    final_resp = final_state.get("final_response", "")
    print("Final Response from Rollback Execution:\n", final_resp)

    # Verify reverse rollback tool invocations: step 2 (stop_container vmid=250) then step 1 (release_ip ip=192.168.1.250)
    assert len(called_rollback_tools) == 2, f"Expected 2 rollback tool calls, got {len(called_rollback_tools)}: {called_rollback_tools}"
    assert called_rollback_tools[0][0] == "proxmox-mcp__stop_container", f"First rollback call should be stop_container, got {called_rollback_tools[0]}"
    assert called_rollback_tools[0][1].get("vmid") == "250" or called_rollback_tools[0][1].get("vmid") == 250
    assert called_rollback_tools[1][0] == "proxmox-mcp__release_ip", f"Second rollback call should be release_ip, got {called_rollback_tools[1]}"
    assert called_rollback_tools[1][1].get("ip") == "192.168.1.250"
    print("✅ Declarative rollback executed in reverse order correctly!")

    # 2. Test Non-Reversible Tool
    log_non_rev = ExecutionLog({"id": 1}, "proxmox-mcp__exec_lxc_command", {"vmid": 100, "command": "rm -rf /tmp/test"})
    log_non_rev.result = {"output": "ok"}
    success_non_rev = execute_rollback_for_step(log_non_rev, tools_catalog)
    assert success_non_rev is False, "Non-reversible tool should return False on rollback"
    assert log_non_rev.rollback_error == "Tool non reversibile"
    print("✅ Non-reversible tool correctly skipped with warning!")

    # 3. Test LLM-based Rollback Planning
    llm_rollback_plan = generate_rollback_plan_with_llm([log_non_rev], "Pulizia file temporanei", "Comando fallito a metà")
    print("\nLLM-Generated Manual Rollback Plan:\n", llm_rollback_plan)
    assert llm_rollback_plan is not None and len(llm_rollback_plan) > 0
    print("✅ LLM-based Rollback Planning correctly generated contextual instructions!")

    # 4. Test Transaction Log (WAL) structure
    assert log_non_rev.to_dict()["timestamp_start"] is not None
    assert log_non_rev.to_dict()["tool_name"] == "proxmox-mcp__exec_lxc_command"
    print("✅ Transaction Log (WAL) structure validated!")

    print("\n==========================================")
    print("ALL PHASE 3 ROLLBACK TESTS PASSED SUCCESSFULLY!")
    print("==========================================")

if __name__ == "__main__":
    test_rollback_engine()
