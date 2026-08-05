import React, { useState } from 'react';
import { Activity, ShieldCheck, ShieldAlert, ChevronDown, ChevronUp, RotateCcw } from 'lucide-react';
import type { ExecutionTraceItem, RollbackAction } from '../api';

interface ExecutionTraceViewerProps {
  trace?: ExecutionTraceItem[];
  rollbackTrace?: RollbackAction[];
  compact?: boolean;
}

export const ExecutionTraceViewer: React.FC<ExecutionTraceViewerProps> = ({
  trace,
  rollbackTrace,
  compact = false,
}) => {
  const [expandedItems, setExpandedItems] = useState<Record<number | string, boolean>>({});

  const hasTrace = Boolean(trace && trace.length > 0);
  const hasRollback = Boolean(rollbackTrace && rollbackTrace.length > 0);

  if (!hasTrace && !hasRollback) return null;

  const toggleExpand = (id: number | string) => {
    setExpandedItems((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className={`space-y-3 ${compact ? '' : 'mt-3 pt-3 border-t border-slate-800'}`}>
      {/* Header */}
      <div className="flex items-center justify-between text-xs text-cyan-400 font-semibold">
        <div className="flex items-center gap-1.5">
          <Activity size={15} />
          <span>Execution Trace ({trace?.length || 0} steps)</span>
        </div>
      </div>

      {/* Trace items */}
      {hasTrace && (
        <div className="space-y-2">
          {trace?.map((tr, idx) => {
            const itemId = tr.step_id || idx;
            const isExpanded = Boolean(expandedItems[itemId]);
            const isSandboxed = tr.sandboxed === true;

            return (
              <div
                key={itemId}
                className="bg-slate-950/80 border border-slate-800 rounded-xl p-2.5 space-y-2 transition"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 font-mono text-xs text-slate-200 truncate">
                    <span className="text-cyan-400 font-bold">Step {idx + 1}:</span>
                    <span className="truncate">{tr.tool_name}</span>
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0">
                    {/* Firecracker Sandbox Badge */}
                    {tr.sandboxed !== undefined && (
                      <span
                        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono border ${
                          isSandboxed
                            ? 'bg-purple-500/10 border-purple-500/30 text-purple-300'
                            : 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                        }`}
                        title={isSandboxed ? 'KVM Firecracker MicroVM Executed' : 'Local Subprocess Fallback'}
                      >
                        {isSandboxed ? <ShieldCheck size={10} /> : <ShieldAlert size={10} />}
                        {isSandboxed ? 'Firecracker' : 'Fallback'}
                      </span>
                    )}

                    {/* Status indicator */}
                    <span
                      className={`text-[10px] font-bold font-mono px-1.5 py-0.5 rounded ${
                        tr.error
                          ? 'bg-rose-500/10 border border-rose-500/30 text-rose-400'
                          : 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-400'
                      }`}
                    >
                      {tr.error ? 'FAILED' : 'OK'}
                    </span>

                    {/* Expand toggle */}
                    {(tr.args || tr.output || tr.result || tr.error) && (
                      <button
                        onClick={() => toggleExpand(itemId)}
                        className="p-1 text-slate-400 hover:text-slate-200 transition"
                        title={isExpanded ? 'Hide details' : 'Show details'}
                      >
                        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    )}
                  </div>
                </div>

                {/* Collapsible Details */}
                {isExpanded && (
                  <div className="pt-2 border-t border-slate-900 space-y-2 text-[11px] font-mono">
                    {tr.args && (
                      <div>
                        <span className="text-slate-500 block mb-0.5">Parameters:</span>
                        <pre className="bg-slate-900/90 p-2 rounded-lg text-slate-300 overflow-x-auto">
                          {JSON.stringify(tr.args, null, 2)}
                        </pre>
                      </div>
                    )}

                    {(tr.output || tr.result) && (
                      <div>
                        <span className="text-slate-500 block mb-0.5">Output:</span>
                        <pre className="bg-slate-900/90 p-2 rounded-lg text-emerald-300 overflow-x-auto whitespace-pre-wrap">
                          {typeof (tr.output || tr.result) === 'string'
                            ? tr.output || tr.result
                            : JSON.stringify(tr.output || tr.result, null, 2)}
                        </pre>
                      </div>
                    )}

                    {tr.error && (
                      <div>
                        <span className="text-rose-400 block mb-0.5">Error detail:</span>
                        <pre className="bg-rose-950/60 p-2 rounded-lg text-rose-300 border border-rose-900/50 overflow-x-auto whitespace-pre-wrap">
                          {tr.error}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Rollback Actions */}
      {hasRollback && (
        <div className="bg-amber-950/40 border border-amber-800/60 rounded-xl p-3 space-y-2">
          <div className="flex items-center gap-1.5 text-xs text-amber-400 font-semibold">
            <RotateCcw size={14} />
            <span>Rollback Actions Executed ({rollbackTrace?.length})</span>
          </div>
          <div className="space-y-1.5 text-xs">
            {rollbackTrace?.map((act, idx) => (
              <div key={idx} className="bg-slate-950/80 p-2 rounded-lg border border-amber-900/40 font-mono text-[11px]">
                <div className="flex items-center justify-between text-amber-300">
                  <span>Undo: {act.tool_name}</span>
                  <span className="text-[10px] text-amber-400/80">{act.status || 'Executed'}</span>
                </div>
                {act.args && (
                  <div className="text-[10px] text-slate-400 mt-1 truncate">
                    Args: {JSON.stringify(act.args)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
