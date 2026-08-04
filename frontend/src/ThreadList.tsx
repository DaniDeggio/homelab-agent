import React, { useState } from 'react';
import type { ThreadItem } from './api';
import { MessageSquare, Plus, Search, RefreshCw, Cpu, X, Trash2, AlertTriangle } from 'lucide-react';

interface ThreadListProps {
  threads: ThreadItem[];
  currentThreadId: string | null;
  onSelectThread: (threadId: string) => void;
  onNewThread: () => void;
  onDeleteThread: (threadId: string) => void;
  onDeleteAllThreads: () => void;
  onRefresh: () => void;
  isLoading: boolean;
  isBackendHealthy: boolean | null;
  onCloseMobile?: () => void;
}

export const ThreadList: React.FC<ThreadListProps> = ({
  threads,
  currentThreadId,
  onSelectThread,
  onNewThread,
  onDeleteThread,
  onDeleteAllThreads,
  onRefresh,
  isLoading,
  isBackendHealthy,
  onCloseMobile,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [showConfirmClearAll, setShowConfirmClearAll] = useState(false);

  const filteredThreads = threads.filter(t => 
    t.thread_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (t.last_message && t.last_message.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  const handleSelect = (id: string) => {
    onSelectThread(id);
    if (onCloseMobile) onCloseMobile();
  };

  const handleCreateNew = () => {
    onNewThread();
    if (onCloseMobile) onCloseMobile();
  };

  const handleDeleteItem = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    onDeleteThread(id);
  };

  const handleConfirmClearAll = () => {
    onDeleteAllThreads();
    setShowConfirmClearAll(false);
  };

  return (
    <div className="w-80 bg-slate-900 border-r border-slate-800 flex flex-col h-full shrink-0 relative">
      {/* App Header */}
      <div className="p-4 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400">
            <Cpu size={18} />
          </div>
          <div>
            <h1 className="font-semibold text-sm text-slate-100 leading-tight">Main-Agent UI</h1>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={`w-2 h-2 rounded-full ${isBackendHealthy === true ? 'bg-emerald-400 animate-pulse' : isBackendHealthy === false ? 'bg-rose-500' : 'bg-amber-400'}`}></span>
              <span className="text-[11px] text-slate-400">
                {isBackendHealthy === true ? 'API Connected' : isBackendHealthy === false ? 'API Offline' : 'Connecting...'}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          {threads.length > 0 && (
            <button
              onClick={() => setShowConfirmClearAll(true)}
              className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded-md transition"
              title="Clear all threads"
            >
              <Trash2 size={15} />
            </button>
          )}
          <button
            onClick={onRefresh}
            disabled={isLoading}
            className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-md transition"
            title="Refresh threads"
          >
            <RefreshCw size={15} className={isLoading ? 'animate-spin' : ''} />
          </button>
          {onCloseMobile && (
            <button
              onClick={onCloseMobile}
              className="md:hidden p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded-md transition"
              title="Close sidebar"
            >
              <X size={18} />
            </button>
          )}
        </div>
      </div>

      {/* Clear All Confirmation Banner */}
      {showConfirmClearAll && (
        <div className="p-3 bg-rose-950/80 border-b border-rose-800 flex flex-col gap-2">
          <div className="flex items-center gap-2 text-xs text-rose-200 font-medium">
            <AlertTriangle size={15} className="text-rose-400 shrink-0" />
            <span>Delete all threads and history?</span>
          </div>
          <div className="flex items-center justify-end gap-2 text-xs">
            <button
              onClick={() => setShowConfirmClearAll(false)}
              className="px-2.5 py-1 text-slate-300 hover:bg-slate-800 rounded transition"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirmClearAll}
              className="px-2.5 py-1 bg-rose-600 hover:bg-rose-500 text-white font-medium rounded transition shadow-sm"
            >
              Clear All
            </button>
          </div>
        </div>
      )}

      {/* New Thread Action */}
      <div className="p-3">
        <button
          onClick={handleCreateNew}
          className="w-full py-2.5 px-3 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium text-xs flex items-center justify-center gap-2 shadow-lg shadow-blue-600/20 transition active:scale-[0.98]"
        >
          <Plus size={16} />
          <span>New Thread</span>
        </button>
      </div>

      {/* Search Input */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-2.5 text-slate-500" />
          <input
            type="text"
            placeholder="Filter threads..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-md pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition"
          />
        </div>
      </div>

      {/* Thread List */}
      <div className="flex-1 overflow-y-auto px-2 py-1 space-y-1">
        {filteredThreads.length === 0 ? (
          <div className="p-4 text-center text-xs text-slate-500">
            {searchTerm ? 'No matching threads found' : 'No active threads yet'}
          </div>
        ) : (
          filteredThreads.map((thread) => {
            const isSelected = thread.thread_id === currentThreadId;
            return (
              <div
                key={thread.thread_id}
                onClick={() => handleSelect(thread.thread_id)}
                className={`w-full text-left p-2.5 rounded-lg border transition flex flex-col gap-1 cursor-pointer group relative ${
                  isSelected
                    ? 'bg-slate-800/90 border-blue-500/40 text-slate-100 shadow-sm'
                    : 'bg-slate-900/50 border-slate-800/60 text-slate-300 hover:bg-slate-800/50 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 font-medium text-xs truncate">
                    <MessageSquare size={14} className={isSelected ? 'text-blue-400' : 'text-slate-400'} />
                    <span className="truncate">{thread.thread_id}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    {thread.checkpoint_count > 0 && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">
                        {thread.checkpoint_count}
                      </span>
                    )}
                    <button
                      onClick={(e) => handleDeleteItem(e, thread.thread_id)}
                      className="opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-rose-400 hover:bg-slate-800 rounded transition"
                      title="Delete thread"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
                {thread.last_message && (
                  <p className="text-[11px] text-slate-400 truncate pl-5">
                    {thread.last_message}
                  </p>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Footer info */}
      <div className="p-3 border-t border-slate-800 text-[11px] text-slate-500 flex items-center justify-between">
        <span>Main-Agent v1.0</span>
        <span className="font-mono text-[10px]">192.168.1.176:8090</span>
      </div>
    </div>
  );
};
