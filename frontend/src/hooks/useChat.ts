import { useState, useCallback, useRef, useEffect } from 'react';
import {
  sendMessage as sendMessageApi,
  getThreadDetails,
  type FormattedMessage,
  type AgentMode,
  type ExecutionTraceItem,
  type PlanStructure,
  type RollbackAction,
} from '../api';
import { adaptChatResponseToMessage, adaptLettaMessagesToMessages } from '../utils/messageAdapter';

export function useChat(currentThreadId: string | null, onThreadCreated?: (id: string) => void) {
  const [threadMessagesMap, setThreadMessagesMap] = useState<Record<string, FormattedMessage[]>>({});
  const [isLoadingChat, setIsLoadingChat] = useState<boolean>(false);
  const [chatError, setChatError] = useState<string | null>(null);

  // Active diagnostics panel state
  const [activeTool, setActiveTool] = useState<string | undefined>(undefined);
  const [activePlan, setActivePlan] = useState<string[] | undefined>(undefined);
  const [activePlanStructure, setActivePlanStructure] = useState<PlanStructure | undefined>(undefined);
  const [activeExecutionTrace, setActiveExecutionTrace] = useState<ExecutionTraceItem[] | undefined>(undefined);
  const [activeRollbackTrace, setActiveRollbackTrace] = useState<RollbackAction[] | undefined>(undefined);
  const [activeMode, setActiveMode] = useState<string | undefined>(undefined);

  const isSendingRef = useRef<boolean>(false);

  // Load history for a thread
  const loadThreadHistory = useCallback(async (threadId: string) => {
    if (isSendingRef.current) return;
    setIsLoadingChat(true);
    try {
      const details = await getThreadDetails(threadId);
      if (details && details.letta_messages) {
        const parsedMsgs = adaptLettaMessagesToMessages(details.letta_messages);
        setThreadMessagesMap((prev) => ({
          ...prev,
          [threadId]: parsedMsgs,
        }));

        // Update diagnostic panel from last assistant message
        const lastAssistant = [...parsedMsgs].reverse().find((m) => m.sender === 'assistant');
        if (lastAssistant) {
          setActiveMode(lastAssistant.mode);
          setActiveTool(lastAssistant.tool_used);
          setActivePlan(lastAssistant.plan_steps);
          setActivePlanStructure(lastAssistant.plan_structure);
          setActiveExecutionTrace(lastAssistant.execution_trace);
          setActiveRollbackTrace(lastAssistant.rollback_trace);
        } else {
          setActiveMode(undefined);
          setActiveTool(undefined);
          setActivePlan(undefined);
          setActivePlanStructure(undefined);
          setActiveExecutionTrace(undefined);
          setActiveRollbackTrace(undefined);
        }
      }
    } catch (err) {
      console.warn(`Could not load history for thread ${threadId}:`, err);
    } finally {
      setIsLoadingChat(false);
    }
  }, []);

  useEffect(() => {
    if (currentThreadId && !isSendingRef.current) {
      loadThreadHistory(currentThreadId);
    }
  }, [currentThreadId, loadThreadHistory]);

  const handleSendMessage = useCallback(
    async (
      input: string,
      mode: AgentMode | undefined,
      execute: boolean
    ) => {
      setChatError(null);
      isSendingRef.current = true;

      const targetThreadId = currentThreadId || `thread_${Date.now()}`;
      if (!currentThreadId && onThreadCreated) {
        onThreadCreated(targetThreadId);
      }

      const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const userMsg: FormattedMessage = {
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
        const response = await sendMessageApi({
          input,
          thread_id: targetThreadId,
          force_mode: mode,
          execute,
        });

        const assistantMsg = adaptChatResponseToMessage(response);

        const finalThreadId = response.thread_id || targetThreadId;

        setThreadMessagesMap((prev) => ({
          ...prev,
          [finalThreadId]: [...(prev[targetThreadId] || []), assistantMsg],
        }));

        // Update Diagnostics
        setActiveTool(response.tool_used);
        setActivePlan(response.plan_steps);
        setActivePlanStructure(response.plan_structure);
        setActiveExecutionTrace(response.execution_trace);
        setActiveRollbackTrace(response.rollback_trace);
        setActiveMode(response.mode);

      } catch (err: any) {
        console.error('API call failed:', err);
        const errMsg = err.response?.data?.detail || err.message || 'Failed to send message to agent';
        setChatError(`API Error: ${errMsg}`);

        const errorMsgItem: FormattedMessage = {
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
    },
    [currentThreadId, onThreadCreated]
  );

  const currentMessages = currentThreadId ? threadMessagesMap[currentThreadId] || [] : [];

  return {
    currentMessages,
    isLoadingChat,
    chatError,
    setChatError,
    handleSendMessage,
    loadThreadHistory,
    diagnostics: {
      activeTool,
      activePlan,
      activePlanStructure,
      activeExecutionTrace,
      activeRollbackTrace,
      activeMode,
    },
  };
}
