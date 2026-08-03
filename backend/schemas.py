from pydantic import BaseModel
from typing import Optional, Literal, List

class ChatRequest(BaseModel):
    input: str
    thread_id: Optional[str] = None
    force_mode: Optional[Literal["chat", "ask", "act", "plan"]] = None
    execute: bool = False

class ChatResponse(BaseModel):
    thread_id: Optional[str] = None
    mode: str
    response: str
    tool_used: Optional[str] = None
    plan_steps: Optional[List[str]] = None

class ThreadSummary(BaseModel):
    thread_id: str
    last_message: Optional[str] = None
    checkpoint_count: int
