from pydantic import BaseModel
from typing import Optional, Literal, List, Dict, Any

class ChatRequest(BaseModel):
    input: str
    thread_id: Optional[str] = None
    force_mode: Optional[Literal["chat", "ask", "act", "plan"]] = None
    reasoning_budget: Optional[int] = None
    execute: bool = False

class ChatResponse(BaseModel):
    thread_id: Optional[str] = None
    mode: str
    response: str
    tool_used: Optional[str] = None
    plan_steps: Optional[List[str]] = None
    plan_structure: Optional[Dict[str, Any]] = None
    execution_trace: Optional[List[Dict[str, Any]]] = None
    reasoning_content: Optional[str] = None


class ThreadSummary(BaseModel):
    thread_id: str
    last_message: Optional[str] = None
    checkpoint_count: int
