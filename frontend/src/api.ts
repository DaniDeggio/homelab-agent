import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE || '/v1';

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
});

export interface ChatRequest {
  input: string;
  thread_id?: string;
  force_mode?: 'chat' | 'ask' | 'act' | 'plan';
  execute?: boolean;
}

export interface ChatResponse {
  thread_id: string | null;
  mode: string;
  response: string;
  tool_used?: string;
  plan_steps?: string[];
}

export interface ThreadItem {
  thread_id: string;
  last_message: string | null;
  checkpoint_count: number;
}

export interface LettaMessage {
  id: string;
  date?: string;
  message_type: 'user_message' | 'assistant_message' | 'system_message' | 'reasoning_message' | 'tool_call_message' | 'tool_return_message' | string;
  content: string | null;
  tool_name?: string;
}

export interface ThreadDetails {
  thread_id: string;
  agent_id?: string;
  checkpoint_count?: number;
  letta_messages?: LettaMessage[];
}

export async function sendMessage(req: ChatRequest): Promise<ChatResponse> {
  const res = await api.post<ChatResponse>('/invoke', req);
  return res.data;
}

export async function listThreads(): Promise<ThreadItem[]> {
  const res = await api.get<ThreadItem[]>('/threads');
  return res.data;
}

export async function getThreadDetails(threadId: string): Promise<ThreadDetails> {
  const res = await api.get<ThreadDetails>(`/threads/${encodeURIComponent(threadId)}`);
  return res.data;
}

export async function checkHealth(): Promise<{ status: string }> {
  const res = await api.get<{ status: string }>('/health');
  return res.data;
}
