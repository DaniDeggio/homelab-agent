import { useState, useEffect, useCallback, useRef } from 'react';
import { ThreadList } from './ThreadList';
import { Chat } from './Chat';
import type { MessageItem } from './Chat';
import { ToolLog } from './ToolLog';
import {
  listThreads,
  sendMessage,
  checkHealth,
  getThreadDetails,
  deleteThread as deleteThreadApi,
  deleteAllThreads as deleteAllThreadsApi,
} from './api';
import type { ThreadItem, LettaMessage } from './api';

export function App() {
  const [threads, setThreads] = useState<ThreadItem[]>([]);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(() => {
    return localStorage.getItem('main_agent_current_thread') || null;
  });
  const [threadMessagesMap, setThreadMessagesMap] = useState<Record<string, MessageItem[]>>({});
  const [isLoadingThreads, setIsLoadingThreads] = useState<boolean>(false);
  const [isLoadingChat, setIsLoadingChat] = useState<boolean>(false);
  const [isBackendHealthy, setIsBackendHealthy] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Ref to track active message sending to prevent loadThreadHistory from wiping state
  const isSendingRef = useRef<boolean>(false);

  // Mobile Drawers Navigation state
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState<boolean>(false);
  const [isMobileToolLogOpen, setIsMobileToolLogOpen] = useState<boolean>(false);

  // Diagnostic states for ToolLog sidebar
  const [activeTool, setActiveTool] = useState<string | undefined>(undefined);
  const [activePlan, setActivePlan] = useState<string[] | undefined>(undefined);
  const [activeMode, setActiveMode] = useState<string | undefined>(undefined);
  const [isToolLogOpen, setIsToolLogOpen] = useState<boolean>(true);

  // Check Backend Health
  const verifyHealth = useCallback(async () => {
    try {
      const res = await checkHealth();
      setIsBackendHealthy(res.status === 'ok');
    } catch {
      setIsBackendHealthy(false);
    }
  }, []);

  // Convert Letta backend messages to UI MessageItems and extract diagnostic metadata
  const parseLettaMessages = (messages: LettaMessage[]): MessageItem[] => {
    const chatMsgs: MessageItem[] = [];

    // Filter relevant user and assistant messages
    const filtered = messages.filter(
      (m) => (m.message_type === 'user_message' || m.message_type === 'assistant_message') && m.content
    );

    // Sort chronologically by date if available
    filtered.sort((a, b) => {
      const dateA = a.date ? new Date(a.date).getTime() : 0;
      const dateB = b.date ? new Date(b.date).getTime() : 0;
      return dateA - dateB;
    });

    filtered.forEach((m, idx) => {
      const timeStr = m.date
        ? new Date(m.date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : '';

      let rawContent = m.content || '';

      // Extract mode from message content if formatted as [Mode: CHAT/ASK/ACT/PLAN]
      let mode: string | undefined = undefined;
      const modeMatch = rawContent.match(/\[Mode:\s*([A-Za-z]+)\]/i);
      if (modeMatch) {
        mode = modeMatch[1].toLowerCase();
      }

      // Extract tool_used
      let tool_used: string | undefined = m.tool_name;
      const toolMatch = rawContent.match(/Tool utilizzato:\s*([^\n]+)/i);
      if (toolMatch) {
        tool_used = toolMatch[1].trim().replace(/`/g, '');
      }

      // Extract plan_steps
      let plan_steps: string[] | undefined = undefined;
      if (rawContent.includes('Passaggi di esecuzione:')) {
        const planSection = rawContent.split('Passaggi di esecuzione:')[1];
        if (planSection) {
          const lines = planSection
            .split('\n')
            .map((l) => l.trim())
            .filter((l) => /^\d+\.\s+/.test(l));
          if (lines.length > 0) {
            plan_steps = lines.map((l) => l.replace(/^\d+\.\s+/, ''));
          }
        }
      }

      const content = rawContent.replace(/\[Mode:\s*[A-Za-z]+\]\n?/i, '').trim();

      chatMsgs.push({
        id: m.id || `msg_${idx}`,
        sender: m.message_type === 'user_message' ? 'user' : 'assistant',
        content,
        timestamp: timeStr,
        mode,
        tool_used,
        plan_steps,
      });
    });

    return chatMsgs;
  };

  // Fetch history for a specific thread from backend and update diagnostic sidebar
  const loadThreadHistory = useCallback(async (threadId: string) => {
    if (isSendingRef.current) return;
    setIsLoadingChat(true);
    try {
      const details = await getThreadDetails(threadId);
      if (details && details.letta_messages) {
        const parsedMsgs = parseLettaMessages(details.letta_messages);
        setThreadMessagesMap((prev) => {
          const existing = prev[threadId] || [];
          if (parsedMsgs.length > 0 || existing.length === 0) {
            return { ...prev, [threadId]: parsedMsgs };
          }
          return prev;
        });

        // Update active diagnostic panel from latest assistant message
        const lastAssistant = [...parsedMsgs].reverse().find((m) => m.sender === 'assistant');
        if (lastAssistant) {
          setActiveMode(lastAssistant.mode);
          setActiveTool(lastAssistant.tool_used);
          setActivePlan(lastAssistant.plan_steps);
        } else {
          setActiveMode(undefined);
          setActiveTool(undefined);
          setActivePlan(undefined);
        }
      }
    } catch (err) {
      console.warn(`Could not load history for thread ${threadId}:`, err);
    } finally {
      setIsLoadingChat(false);
    }
  }, []);

  // Fetch threads list
  const loadThreads = useCallback(async () => {
    setIsLoadingThreads(true);
    try {
      const data = await listThreads();
      setThreads(data);

      const savedThread = localStorage.getItem('main_agent_current_thread');
      if (savedThread && data.some((t) => t.thread_id === savedThread)) {
        setCurrentThreadId((prev) => prev || savedThread);
      } else if (data.length > 0) {
        setCurrentThreadId((prev) => prev || data[0].thread_id);
      }
    } catch (err: any) {
      console.error('Failed to load threads:', err);
      setError('Unable to reach Main Agent API. Make sure the backend service is running.');
    } finally {
      setIsLoadingThreads(false);
    }
  }, []);

  // Load history whenever currentThreadId changes
  useEffect(() => {
    if (currentThreadId && !isSendingRef.current) {
      localStorage.setItem('main_agent_current_thread', currentThreadId);
      loadThreadHistory(currentThreadId);
    }
  }, [currentThreadId, loadThreadHistory]);

  useEffect(() => {
    verifyHealth();
    loadThreads();
    const interval = setInterval(verifyHealth, 15000);
    return () => clearInterval(interval);
  }, [verifyHealth, loadThreads]);

  // Handle New Thread creation
  const handleNewThread = () => {
    const newId = `thread_${Date.now()}`;
    setCurrentThreadId(newId);
    localStorage.setItem('main_agent_current_thread', newId);
    setThreadMessagesMap((prev) => ({ ...prev, [newId]: [] }));
    setActiveTool(undefined);
    setActivePlan(undefined);
    setActiveMode(undefined);
    setIsMobileSidebarOpen(false);
  };

  // Handle Thread selection
  const handleSelectThread = (id: string) => {
    if (id === currentThreadId) return;
    setCurrentThreadId(id);
    localStorage.setItem('main_agent_current_thread', id);
    setError(null);
    loadThreadHistory(id);
    setIsMobileSidebarOpen(false);
  };

  // Handle Delete Single Thread
  const handleDeleteThread = async (threadId: string) => {
    try {
      await deleteThreadApi(threadId);
      setThreads((prev) => prev.filter((t) => t.thread_id !== threadId));
      setThreadMessagesMap((prev) => {
        const copy = { ...prev };
        delete copy[threadId];
        return copy;
      });

      if (currentThreadId === threadId) {
        const remaining = threads.filter((t) => t.thread_id !== threadId);
        if (remaining.length > 0) {
          const nextId = remaining[0].thread_id;
          setCurrentThreadId(nextId);
          localStorage.setItem('main_agent_current_thread', nextId);
        } else {
          setCurrentThreadId(null);
          localStorage.removeItem('main_agent_current_thread');
          setActiveMode(undefined);
          setActiveTool(undefined);
          setActivePlan(undefined);
        }
      }
    } catch (err: any) {
      console.error('Failed to delete thread:', err);
      setError(`Failed to delete thread ${threadId}`);
    }
  };

  // Handle Delete All Threads
  const handleDeleteAllThreads = async () => {
    try {
      await deleteAllThreadsApi();
      setThreads([]);
      setThreadMessagesMap({});
      setCurrentThreadId(null);
      localStorage.removeItem('main_agent_current_thread');
      setActiveMode(undefined);
      setActiveTool(undefined);
      setActivePlan(undefined);
    } catch (err: any) {
      console.error('Failed to clear threads:', err);
      setError('Failed to clear threads');
    }
  };

  // Handle Send Message
  const handleSendMessage = async (
    input: string,
    mode: 'chat' | 'ask' | 'act' | 'plan' | undefined,
    execute: boolean
  ) => {
    setError(null);
    isSendingRef.current = true;

    const targetThreadId = currentThreadId || `thread_${Date.now()}`;
    if (!currentThreadId) {
      setCurrentThreadId(targetThreadId);
      localStorage.setItem('main_agent_current_thread', targetThreadId);
    }

    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const userMsg: MessageItem = {
      id: `user_${Date.now()}`,
      sender: 'user',
      content: input,
      timestamp,
    };

    setThreadMessagesMap((prev) => ({
      ...prev,
      [targetThreadId]: [...(prev[targetThreadId] || []), userMsg],
    }));

    setIsLoadingChat(true);

    try {
      const response = await sendMessage({
        input,
        thread_id: targetThreadId,
        force_mode: mode,
        execute,
      });

      const assistantMsg: MessageItem = {
        id: `ast_${Date.now()}`,
        sender: 'assistant',
        content: (response.response || '(No content returned)').replace(/\[Mode:\s*[A-Za-z]+\]\n?/i, '').trim(),
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        mode: response.mode,
        tool_used: response.tool_used,
        plan_steps: response.plan_steps,
      };

      const finalThreadId = response.thread_id || targetThreadId;
      if (finalThreadId !== currentThreadId) {
        setCurrentThreadId(finalThreadId);
        localStorage.setItem('main_agent_current_thread', finalThreadId);
      }

      setThreadMessagesMap((prev) => ({
        ...prev,
        [finalThreadId]: [...(prev[targetThreadId] || []), assistantMsg],
      }));

      // Update ToolLog diagnostics
      setActiveTool(response.tool_used);
      setActivePlan(response.plan_steps);
      setActiveMode(response.mode);

      // Refresh threads list sidebar
      loadThreads();

    } catch (err: any) {
      console.error('API call failed:', err);
      const errMsg = err.response?.data?.detail || err.message || 'Failed to send message to agent';
      setError(`API Error: ${errMsg}`);

      const errorMsgItem: MessageItem = {
        id: `err_${Date.now()}`,
        sender: 'assistant',
        content: `Error: ${errMsg}`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        isError: true,
      };

      setThreadMessagesMap((prev) => ({
        ...prev,
        [targetThreadId]: [...(prev[targetThreadId] || []), errorMsgItem],
      }));
    } finally {
      setIsLoadingChat(false);
      isSendingRef.current = false;
    }
  };

  const currentMessages = currentThreadId ? threadMessagesMap[currentThreadId] || [] : [];

  return (
    <div className="flex h-dvh w-screen bg-slate-950 overflow-hidden font-sans relative">
      {/* Mobile Backdrop Overlay */}
      {(isMobileSidebarOpen || isMobileToolLogOpen) && (
        <div
          onClick={() => {
            setIsMobileSidebarOpen(false);
            setIsMobileToolLogOpen(false);
          }}
          className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-40 md:hidden transition-opacity"
        />
      )}

      {/* Left Sidebar: Threads (Responsive Drawer) */}
      <div
        className={`fixed md:relative inset-y-0 left-0 z-50 md:z-auto transform ${
          isMobileSidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        } transition-transform duration-300 ease-in-out flex shrink-0`}
      >
        <ThreadList
          threads={threads}
          currentThreadId={currentThreadId}
          onSelectThread={handleSelectThread}
          onNewThread={handleNewThread}
          onDeleteThread={handleDeleteThread}
          onDeleteAllThreads={handleDeleteAllThreads}
          onRefresh={() => {
            loadThreads();
            if (currentThreadId) loadThreadHistory(currentThreadId);
          }}
          isLoading={isLoadingThreads}
          isBackendHealthy={isBackendHealthy}
          onCloseMobile={() => setIsMobileSidebarOpen(false)}
        />
      </div>

      {/* Main Area: Chat */}
      <Chat
        currentThreadId={currentThreadId}
        messages={currentMessages}
        onSendMessage={handleSendMessage}
        isLoading={isLoadingChat}
        error={error}
        onClearError={() => setError(null)}
        onOpenMobileSidebar={() => setIsMobileSidebarOpen(true)}
        onOpenMobileToolLog={() => setIsMobileToolLogOpen(true)}
      />

      {/* Right Sidebar: Tool & Plan Log (Responsive Drawer) */}
      <div
        className={`fixed md:relative inset-y-0 right-0 z-50 md:z-auto transform ${
          isMobileToolLogOpen ? 'translate-x-0' : 'translate-x-full md:translate-x-0'
        } transition-transform duration-300 ease-in-out flex shrink-0`}
      >
        <ToolLog
          toolUsed={activeTool}
          planSteps={activePlan}
          mode={activeMode}
          isOpen={isToolLogOpen}
          onToggle={() => setIsToolLogOpen(!isToolLogOpen)}
          onCloseMobile={() => setIsMobileToolLogOpen(false)}
        />
      </div>
    </div>
  );
}

export default App;
