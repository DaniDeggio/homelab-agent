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
    effective_thread_id = thread_id or "default"
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
    
    cfg = {"configurable": {"thread_id": effective_thread_id}}
    try:
        final_state = app_graph.invoke(initial_state, config=cfg)
        
        mode = final_state.get("mode", force_mode or "plan")
        response_text = final_state.get("final_response", "")
        plan_dict = final_state.get("plan", {})
        tool_used = plan_dict.get("tool_name") if isinstance(plan_dict, dict) else None
        
        plan_steps = plan_dict.get("plan_steps") if isinstance(plan_dict, dict) else None
            
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
        cursor.execute("SELECT thread_id, COUNT(*) FROM checkpoints GROUP BY thread_id ORDER BY rowid DESC")
        rows = cursor.fetchall()
        conn.close()
        
        summaries = []
        for tid, count in rows:
            if not tid:
                continue
            summaries.append(ThreadSummary(
                thread_id=tid,
                last_message=None,
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
        raw_messages = letta_client.get_messages(agent_id) if agent_id else []
        clean_messages = letta_client.filter_clean_messages(raw_messages)
        
        return {
            "thread_id": thread_id,
            "agent_id": agent_id,
            "checkpoint_count": count,
            "letta_messages": clean_messages
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get thread details: {str(e)}")

@api.delete("/v1/threads/{thread_id}", dependencies=[Depends(verify_api_key)])
async def delete_single_thread(thread_id: str):
    try:
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        deleted_rows = cursor.rowcount
        conn.commit()
        conn.close()

        # Delete from Letta if agent exists
        agent_id = letta_client.create_thread(thread_id)
        if agent_id:
            letta_client.delete_thread(agent_id)

        return {"status": "deleted", "thread_id": thread_id, "deleted_checkpoints": deleted_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete thread '{thread_id}': {str(e)}")

@api.delete("/v1/threads", dependencies=[Depends(verify_api_key)])
async def delete_all_threads():
    try:
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM checkpoints")
        deleted_rows = cursor.rowcount
        conn.commit()
        conn.close()

        return {"status": "cleared", "deleted_checkpoints": deleted_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear threads: {str(e)}")

