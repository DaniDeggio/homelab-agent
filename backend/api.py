import os
import time
import json
import sqlite3
import queue
import threading
import contextvars
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from schemas import ChatRequest, ChatResponse, ThreadSummary
from graph import build_graph, stream_queue
import letta_client
import thread_store
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

def run_agent_flow(task: str, thread_id: Optional[str], force_mode: Optional[str] = None, execute: bool = False, reasoning_budget: Optional[int] = None) -> ChatResponse:
    effective_thread_id = thread_id or f"thread_{int(time.time() * 1000)}"
    initial_state = {
        "task": task,
        "thread_id": effective_thread_id,
        "force_mode": force_mode,
        "reasoning_budget": reasoning_budget,
        "execute": execute,
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
        plan_structure = final_state.get("plan_structure") or (plan_dict.get("plan_structure") if isinstance(plan_dict, dict) else None)
        execution_trace = final_state.get("execution_trace") or (plan_dict.get("execution_log") if isinstance(plan_dict, dict) else None)
        rollback_trace = final_state.get("rollback_trace")
        reasoning_content = final_state.get("reasoning_content")
            
        resp = ChatResponse(
            thread_id=effective_thread_id,
            mode=mode,
            response=response_text,
            tool_used=tool_used,
            plan_steps=plan_steps,
            plan_structure=plan_structure,
            execution_trace=execution_trace,
            rollback_trace=rollback_trace,
            reasoning_content=reasoning_content
        )

        # Salva atomico del turno nello store SQLite
        thread_store.save_turn(effective_thread_id, task, resp.model_dump())

        return resp

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph execution failed: {str(e)}")

@api.get("/v1/health")
async def health():
    return {"status": "ok"}

@api.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def chat_endpoint(req: ChatRequest):
    return run_agent_flow(req.input, req.thread_id, force_mode=req.force_mode, execute=req.execute, reasoning_budget=req.reasoning_budget)

@api.post("/v1/ask", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def ask_endpoint(req: ChatRequest):
    return run_agent_flow(req.input, req.thread_id, force_mode="ask", execute=req.execute, reasoning_budget=req.reasoning_budget)

@api.post("/v1/act", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def act_endpoint(req: ChatRequest):
    return run_agent_flow(req.input, req.thread_id, force_mode="act", execute=req.execute, reasoning_budget=req.reasoning_budget)

@api.post("/v1/plan", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def plan_endpoint(req: ChatRequest):
    return run_agent_flow(req.input, req.thread_id, force_mode="plan", execute=req.execute, reasoning_budget=req.reasoning_budget)

@api.post("/v1/invoke", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def invoke_endpoint(req: ChatRequest):
    return run_agent_flow(req.input, req.thread_id, force_mode=req.force_mode, execute=req.execute, reasoning_budget=req.reasoning_budget)

def run_agent_flow_stream(task: str, thread_id: Optional[str], force_mode: Optional[str] = None, execute: bool = False, reasoning_budget: Optional[int] = None):
    effective_thread_id = thread_id or f"thread_{int(time.time() * 1000)}"
    initial_state = {
        "task": task,
        "thread_id": effective_thread_id,
        "force_mode": force_mode,
        "reasoning_budget": reasoning_budget,
        "execute": execute,
        "agent_id": None,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": ""
    }
    
    cfg = {"configurable": {"thread_id": effective_thread_id}}
    q = queue.Queue()
    stream_queue.set(q)
    
    def worker():
        try:
            final_state = app_graph.invoke(initial_state, config=cfg)
            mode = final_state.get("mode", force_mode or "plan")
            response_text = final_state.get("final_response", "")
            plan_dict = final_state.get("plan", {})
            tool_used = plan_dict.get("tool_name") if isinstance(plan_dict, dict) else None
            plan_steps = plan_dict.get("plan_steps") if isinstance(plan_dict, dict) else None
            plan_structure = final_state.get("plan_structure") or (plan_dict.get("plan_structure") if isinstance(plan_dict, dict) else None)
            execution_trace = final_state.get("execution_trace") or (plan_dict.get("execution_log") if isinstance(plan_dict, dict) else None)
            rollback_trace = final_state.get("rollback_trace")
            reasoning_content = final_state.get("reasoning_content")
                
            resp = ChatResponse(
                thread_id=effective_thread_id,
                mode=mode,
                response=response_text,
                tool_used=tool_used,
                plan_steps=plan_steps,
                plan_structure=plan_structure,
                execution_trace=execution_trace,
                rollback_trace=rollback_trace,
                reasoning_content=reasoning_content
            )
            thread_store.save_turn(effective_thread_id, task, resp.model_dump())
            q.put({"type": "final", "response": resp.model_dump()})
        except Exception as e:
            q.put({"type": "error", "error": str(e)})
        finally:
            q.put(None)
            
    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(worker,))
    t.start()
    
    def event_generator():
        while True:
            item = q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@api.post("/v1/invoke_stream", dependencies=[Depends(verify_api_key)])
async def invoke_stream_endpoint(req: ChatRequest):
    return run_agent_flow_stream(req.input, req.thread_id, force_mode=req.force_mode, execute=req.execute, reasoning_budget=req.reasoning_budget)

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
            last_msg = thread_store.get_last_message(tid)

            # Se non c'è last_message, tenta backfill da LangGraph per popolare lo store
            if last_msg is None and count > 0:
                backfilled = thread_store.backfill_from_state_history(tid, app_graph)
                if backfilled:
                    last_msg = thread_store.get_last_message(tid)

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
        
        # 1. Prova lo store locale (istantaneo)
        stored_messages = thread_store.get_thread_messages(thread_id)

        # 2. Se vuoto ma il thread ha checkpoint, ricostruisci da LangGraph state history
        if not stored_messages and count > 0:
            stored_messages = thread_store.backfill_from_state_history(thread_id, app_graph)

        # 3. Letta come fonte supplementare opzionale (mai bloccante)
        clean_messages = []
        agent_id = None
        try:
            agent_id = letta_client.create_thread(thread_id)
            if agent_id:
                raw_messages = letta_client.get_messages(agent_id)
                clean_messages = letta_client.filter_clean_messages(raw_messages) if raw_messages else []
        except Exception as letta_err:
            import logging
            logging.getLogger("api").warning(f"Letta non raggiungibile per thread '{thread_id}': {letta_err}")

        return {
            "thread_id": thread_id,
            "agent_id": agent_id,
            "checkpoint_count": count,
            "messages": stored_messages,
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

        thread_store.delete_thread_messages(thread_id)

        # Delete from Letta if agent exists (non-blocking)
        try:
            agent_id = letta_client.create_thread(thread_id)
            if agent_id:
                letta_client.delete_thread(agent_id)
        except Exception:
            pass

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

        thread_store.clear_all_thread_messages()

        return {"status": "cleared", "deleted_checkpoints": deleted_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear threads: {str(e)}")

