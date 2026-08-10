import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE || '/v1';

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
});

export type AgentMode = 'chat' | 'ask' | 'act' | 'plan';

export interface ChatRequest {
  input: string;
  thread_id?: string;
  force_mode?: AgentMode;
  reasoning_budget?: number;
  execute?: boolean;
}

export interface ExecutionTraceItem {
  step_id?: number | string;
  tool_name: string;
  args?: Record<string, any>;
  output?: any;
  result?: any;
  error?: string;
  reasoning?: string;
  execution_time_ms?: number;
  sandboxed?: boolean;
  timestamp?: string;
}

export interface PlanNode {
  id: string;
  tool_name: string;
  args?: Record<string, any>;
  depends_on?: string[];
  description?: string;
  status?: 'pending' | 'running' | 'success' | 'failed' | 'rolled_back';
  output_var?: string;
}

export interface PlanStructure {
  goal?: string;
  nodes?: PlanNode[];
  edges?: Array<{ from: string; to: string }>;
}

export interface RollbackAction {
  tool_name: string;
  args?: Record<string, any>;
  status?: string;
  timestamp?: string;
  error?: string;
}

export interface ChatResponse {
  thread_id: string | null;
  mode: AgentMode | string;
  response: string;
  tool_used?: string;
  plan_steps?: string[];
  plan_structure?: PlanStructure;
  execution_trace?: ExecutionTraceItem[];
  rollback_trace?: RollbackAction[];
  reasoning_content?: string;
  error?: string;
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
  metadata?: Record<string, any>;
}

export interface ThreadDetails {
  thread_id: string;
  agent_id?: string;
  checkpoint_count?: number;
  messages?: FormattedMessage[];
  letta_messages?: LettaMessage[];
}

export interface FormattedMessage {
  id: string;
  sender: 'user' | 'assistant';
  content: string;
  timestamp: string;
  mode?: AgentMode | string;
  tool_used?: string;
  reasoning?: string;
  plan_steps?: string[];
  plan_structure?: PlanStructure;
  execution_trace?: ExecutionTraceItem[];
  rollback_trace?: RollbackAction[];
  reasoning_content?: string;
  isError?: boolean;
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

export async function deleteThread(threadId: string): Promise<{ status: string }> {
  const res = await api.delete<{ status: string }>(`/threads/${encodeURIComponent(threadId)}`);
  return res.data;
}

export async function deleteAllThreads(): Promise<{ status: string }> {
  const res = await api.delete<{ status: string }>('/threads');
  return res.data;
}
