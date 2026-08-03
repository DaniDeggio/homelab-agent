import os
import sqlite3
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from schemas import ChatRequest, ChatResponse, ThreadSummary
from graph import build_graph
import letta_client
import config

app_graph = build_graph()

api = FastAPI(
    title="Home Lab Agent API",
    description="FastAPI service exposing LangGraph Agent with MetaMCP tools, Letta persistent memory, and SQLite Checkpointing",
    version="1.0"
)

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(x_api_key: Optional[str] = Security(api_key_header)):
    expected_key = os.getenv("API_SECRET_KEY", "").strip()
    if expected_key:
        if not x_api_key or x_api_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
    return x_api_key

def run_agent_flow(task: str, thread_id: Optional[str], force_mode: Optional[str] = None) -> ChatResponse:
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
    
    cfg = {"configurable": {"thread_id": thread_id}} if thread_id else {}
    try:
        final_state = app_graph.invoke(initial_state, config=cfg)
        
        mode = final_state.get("mode", force_mode or "plan")
        response_text = final_state.get("final_response", "")
        plan_dict = final_state.get("plan", {})
        tool_used = plan_dict.get("tool_name") if isinstance(plan_dict, dict) else None
        
        plan_steps = None
        if mode == "plan":
            plan_steps = [
                "1. Allocazione VMID e verifica template LXC Debian",
                "2. Assegnazione IP statico libero da IPAM",
                "3. Creazione record DNS Pi-hole per il dominio richiesto",
                "4. Configurazione Host Proxy Nginx Manager (NPM) per il forwarding HTTP/HTTPS",
                "5. Avvio e bootstrap del container con Agy"
            ]
            
        return ChatResponse(
            thread_id=thread_id,
            mode=mode,
            response=response_text,
            tool_used=tool_used,
            plan_steps=plan_steps
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph execution failed: {str(e)}")

@api.get("/v1/health")
async def health():
    return {"status": "ok"}

@api.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def chat_endpoint(req: ChatRequest):
    return run_agent_flow(req.input, req.thread_id, force_mode="chat")

@api.post("/v1/ask", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def ask_endpoint(req: ChatRequest):
    return run_agent_flow(req.input, req.thread_id, force_mode="ask")

@api.post("/v1/act", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def act_endpoint(req: ChatRequest):
    return run_agent_flow(req.input, req.thread_id, force_mode="act")

@api.post("/v1/plan", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def plan_endpoint(req: ChatRequest):
    return run_agent_flow(req.input, req.thread_id, force_mode="plan")

@api.post("/v1/invoke", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def invoke_endpoint(req: ChatRequest):
    return run_agent_flow(req.input, req.thread_id, force_mode=req.force_mode)

@api.get("/v1/threads", response_model=List[ThreadSummary], dependencies=[Depends(verify_api_key)])
async def list_threads():
    try:
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT thread_id, COUNT(*) FROM checkpoints GROUP BY thread_id")
        rows = cursor.fetchall()
        conn.close()
        
        summaries = []
        for tid, count in rows:
            if not tid:
                continue
            last_msg = None
            agent_id = letta_client.create_thread(tid)
            if agent_id:
                msgs = letta_client.get_messages(agent_id, limit=5)
                if msgs and isinstance(msgs, list):
                    for m in reversed(msgs):
                        if isinstance(m, dict):
                            txt = m.get("text") or m.get("content") or m.get("message")
                            if txt and "system" not in str(m.get("message_type") or m.get("role") or "").lower():
                                last_msg = str(txt)[:100]
                                break
            summaries.append(ThreadSummary(
                thread_id=tid,
                last_message=last_msg,
                checkpoint_count=count
            ))
        return summaries
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list threads: {str(e)}")

@api.get("/v1/threads/{thread_id}", dependencies=[Depends(verify_api_key)])
async def get_thread(thread_id: str):
    try:
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (thread_id,))
        count = cursor.fetchone()[0]
        conn.close()
        
        agent_id = letta_client.create_thread(thread_id)
        letta_messages = letta_client.get_messages(agent_id) if agent_id else []
        
        return {
            "thread_id": thread_id,
            "agent_id": agent_id,
            "checkpoint_count": count,
            "letta_messages": letta_messages
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get thread details: {str(e)}")
