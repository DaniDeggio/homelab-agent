from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class ModePolicy(BaseModel):
    mode: str
    max_tool_calls: int
    allowed_registries: List[str]
    allow_react_loop: bool
    timeout_seconds: int

DEFAULT_MODE_POLICIES: Dict[str, ModePolicy] = {
    "chat": ModePolicy(
        mode="chat",
        max_tool_calls=1,
        allowed_registries=["web"],
        allow_react_loop=True,
        timeout_seconds=15
    ),
    "ask": ModePolicy(
        mode="ask",
        max_tool_calls=3,
        allowed_registries=["web", "code"],
        allow_react_loop=True,
        timeout_seconds=30
    ),
    "act": ModePolicy(
        mode="act",
        max_tool_calls=10,
        allowed_registries=["metamcp", "web", "code"],
        allow_react_loop=True,
        timeout_seconds=120
    ),
    "plan": ModePolicy(
        mode="plan",
        max_tool_calls=15,
        allowed_registries=["metamcp", "web", "code"],
        allow_react_loop=True,
        timeout_seconds=300
    ),
}

def get_mode_policy(mode: str) -> ModePolicy:
    """Restituisce la policy associata a una determinata modalità (default chat)."""
    clean_mode = (mode or "chat").lower().strip()
    return DEFAULT_MODE_POLICIES.get(clean_mode, DEFAULT_MODE_POLICIES["chat"])
