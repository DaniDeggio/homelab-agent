import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Wrench, ListChecks, Sparkles, AlertTriangle, Play } from 'lucide-react';

export interface MessageItem {
  id: string;
  sender: 'user' | 'assistant';
  content: string;
  timestamp: string;
  mode?: string;
  tool_used?: string;
  plan_steps?: string[];
  isError?: boolean;
}

interface ChatProps {
  currentThreadId: string | null;
  messages: MessageItem[];
  onSendMessage: (input: string, mode: 'chat' | 'ask' | 'act' | 'plan' | undefined, execute: boolean) => Promise<void>;
  isLoading: boolean;
  error: string | null;
  onClearError: () => void;
}

export const Chat: React.FC<ChatProps> = ({
  currentThreadId,
  messages,
  onSendMessage,
  isLoading,
  error,
  onClearError,
}) => {
  const [input, setInput] = useState('');
  const [selectedMode, setSelectedMode] = useState<'chat' | 'ask' | 'act' | 'plan' | 'auto'>('auto');
  const [execute, setExecute] = useState<boolean>(true);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim() || isLoading) return;

    const modeToPass = selectedMode === 'auto' ? undefined : selectedMode;
    onSendMessage(input.trim(), modeToPass, execute);
    setInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-slate-950 text-slate-100 overflow-hidden relative">
      {/* Top Header */}
      <div className="h-14 border-b border-slate-800 bg-slate-900/60 backdrop-blur-md px-6 flex items-center justify-between z-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center text-white shadow-md shadow-blue-500/20">
            <Bot size={18} />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-200">
              {currentThreadId ? `Thread: ${currentThreadId}` : 'New Session'}
            </h2>
            <p className="text-[11px] text-slate-400">Main Agent FastAPI Engine</p>
          </div>
        </div>

        {/* Mode Selector Controls */}
        <div className="flex items-center gap-2">
          <div className="bg-slate-900 border border-slate-800 rounded-lg p-1 flex items-center gap-1 text-xs">
            <span className="text-slate-400 text-[11px] px-2 font-medium">Mode:</span>
            {(['auto', 'chat', 'ask', 'act', 'plan'] as const).map((modeOption) => (
              <button
                key={modeOption}
                onClick={() => setSelectedMode(modeOption)}
                className={`px-2.5 py-1 rounded-md text-xs font-medium capitalize transition ${
                  selectedMode === modeOption
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                }`}
              >
                {modeOption}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer bg-slate-900 border border-slate-800 px-2.5 py-1.5 rounded-lg hover:border-slate-700">
            <input
              type="checkbox"
              checked={execute}
              onChange={(e) => setExecute(e.target.checked)}
              className="rounded bg-slate-950 border-slate-700 text-blue-600 focus:ring-0"
            />
            <Play size={12} className={execute ? 'text-emerald-400' : 'text-slate-500'} />
            <span className="text-[11px]">Execute</span>
          </label>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="bg-rose-950/80 border-b border-rose-800 px-6 py-2.5 flex items-center justify-between text-xs text-rose-200">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} className="text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            onClick={onClearError}
            className="text-rose-400 hover:text-rose-200 font-bold px-2 py-0.5"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Messages Scroll Container */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-8 text-slate-500 space-y-4">
            <div className="w-14 h-14 rounded-2xl bg-slate-900 border border-slate-800 flex items-center justify-center text-blue-400">
              <Sparkles size={28} />
            </div>
            <div className="max-w-md space-y-1">
              <h3 className="text-slate-300 font-semibold text-sm">Main Agent Ready</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Type a prompt to interact with the main agent API. Switch between <span className="text-blue-400 font-mono">chat</span>, <span className="text-blue-400 font-mono">ask</span>, <span className="text-blue-400 font-mono">act</span>, or <span className="text-blue-400 font-mono">plan</span> modes above.
              </p>
            </div>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex gap-3 max-w-3xl ${
                msg.sender === 'user' ? 'ml-auto flex-row-reverse' : 'mr-auto'
              }`}
            >
              {/* Avatar */}
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-white shadow-sm ${
                  msg.sender === 'user'
                    ? 'bg-blue-600'
                    : msg.isError
                    ? 'bg-rose-600'
                    : 'bg-slate-800 border border-slate-700'
                }`}
              >
                {msg.sender === 'user' ? <User size={16} /> : <Bot size={16} />}
              </div>

              {/* Message Content Bubble */}
              <div className="flex flex-col space-y-2 max-w-xl">
                <div
                  className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                    msg.sender === 'user'
                      ? 'bg-blue-600 text-white rounded-tr-none shadow-md shadow-blue-600/10'
                      : msg.isError
                      ? 'bg-rose-950/60 border border-rose-800/80 text-rose-200 rounded-tl-none'
                      : 'bg-slate-900 border border-slate-800 text-slate-100 rounded-tl-none shadow-sm'
                  }`}
                >
                  <div className="whitespace-pre-wrap font-sans">{msg.content}</div>

                  {/* Multi-step Plan list embedded in bubble */}
                  {msg.plan_steps && msg.plan_steps.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-slate-800 space-y-2">
                      <div className="flex items-center gap-1.5 text-xs text-indigo-400 font-medium">
                        <ListChecks size={14} />
                        <span>Execution Plan ({msg.plan_steps.length} steps):</span>
                      </div>
                      <ol className="space-y-1.5 text-xs">
                        {msg.plan_steps.map((step, idx) => (
                          <li key={idx} className="flex items-start gap-2 bg-slate-950/60 p-2 rounded-lg border border-slate-800/80">
                            <span className="font-mono font-bold text-indigo-400 text-[11px] min-w-[18px]">
                              {idx + 1}.
                            </span>
                            <span className="text-slate-300">{step}</span>
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}
                </div>

                {/* Sub-bubble Meta (Tool Used Badge & Timestamp) */}
                <div
                  className={`flex items-center gap-2 px-1 text-[11px] text-slate-500 ${
                    msg.sender === 'user' ? 'justify-end' : 'justify-start'
                  }`}
                >
                  <span>{msg.timestamp}</span>
                  {msg.mode && (
                    <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 font-mono text-[10px] text-slate-400">
                      {msg.mode}
                    </span>
                  )}
                  {msg.tool_used && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 font-mono text-[10px]">
                      <Wrench size={10} />
                      {msg.tool_used}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))
        )}

        {/* Loading Indicator */}
        {isLoading && (
          <div className="flex gap-3 max-w-3xl mr-auto items-center">
            <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-blue-400 animate-pulse">
              <Bot size={16} />
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-2xl rounded-tl-none px-4 py-3 text-slate-400 text-xs flex items-center gap-2">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
              </div>
              <span className="ml-1">Agent thinking & executing...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Bar */}
      <div className="p-4 border-t border-slate-800 bg-slate-900/80 backdrop-blur-md">
        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto relative flex items-center">
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              currentThreadId
                ? `Send message to thread '${currentThreadId}'... (Shift+Enter for newline)`
                : 'Send message... (Shift+Enter for newline)'
            }
            className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-4 pr-12 py-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 resize-none transition"
          />
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            className="absolute right-2 p-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:hover:bg-blue-600 text-white rounded-lg transition active:scale-95 shadow-md shadow-blue-600/20"
            title="Send Message"
          >
            <Send size={16} />
          </button>
        </form>
      </div>
    </div>
  );
};
