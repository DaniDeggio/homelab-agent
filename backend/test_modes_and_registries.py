import unittest
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mode_policy import get_mode_policy, DEFAULT_MODE_POLICIES
from registry.manager import get_registry_manager
from registry.web_search import WebSearchRegistry
from registry.code_exec import CodeExecRegistry
from agent_loop import run_agent_loop

class TestModesAndRegistries(unittest.TestCase):
    def test_mode_policies(self):
        chat_p = get_mode_policy("chat")
        self.assertEqual(chat_p.max_tool_calls, 0)
        self.assertEqual(len(chat_p.allowed_registries), 0)

        ask_p = get_mode_policy("ask")
        self.assertEqual(ask_p.max_tool_calls, 2)
        self.assertIn("web", ask_p.allowed_registries)
        self.assertIn("code", ask_p.allowed_registries)

        act_p = get_mode_policy("act")
        self.assertIn("metamcp", act_p.allowed_registries)
        self.assertEqual(act_p.max_tool_calls, 10)

    def test_registry_manager(self):
        mgr = get_registry_manager()
        tools_ask = mgr.get_tools_for_mode(["web", "code"])
        names = [t["name"] for t in tools_ask]
        self.assertIn("web_search", names)
        self.assertIn("python_interpreter", names)

    def test_code_exec_fallback(self):
        reg = CodeExecRegistry()
        res = reg.execute_tool("python_interpreter", {"code": "print(2 + 2)"})
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("output"), "4")
        self.assertIn("sandboxed", res)
        # Should fallback to False since we don't have kernel/rootfs in test environment
        self.assertFalse(res.get("sandboxed"))

    def test_agent_loop_chat_mode(self):
        def dummy_llm(prompt, system_prompt=None):
            return "Ciao! Risposta chat mock."

        res = run_agent_loop(
            task="Ciao chi sei?",
            mode="chat",
            call_llm_fn=dummy_llm
        )
        self.assertEqual(res["final_response"], "Ciao! Risposta chat mock.")
        self.assertEqual(len(res["execution_trace"]), 0)

if __name__ == "__main__":
    unittest.main()
