import React from 'react';
import { ListChecks, Play, GitBranch, CheckCircle2, Clock, XCircle, RotateCcw } from 'lucide-react';
import type { PlanStructure, PlanNode } from '../api';

interface PlanViewerProps {
  planSteps?: string[];
  planStructure?: PlanStructure;
  onExecutePlan?: (stepsSummary: string) => void;
  isLoading?: boolean;
  compact?: boolean;
}

export const PlanViewer: React.FC<PlanViewerProps> = ({
  planSteps,
  planStructure,
  onExecutePlan,
  isLoading = false,
  compact = false,
}) => {
  const hasSteps = Boolean(planSteps && planSteps.length > 0);
  const hasNodes = Boolean(planStructure?.nodes && planStructure.nodes.length > 0);

  if (!hasSteps && !hasNodes) return null;

  const renderStatusBadge = (status?: PlanNode['status']) => {
    switch (status) {
      case 'success':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[10px] font-medium border border-emerald-500/20">
            <CheckCircle2 size={10} /> Success
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-400 text-[10px] font-medium border border-rose-500/20">
            <XCircle size={10} /> Failed
          </span>
        );
      case 'rolled_back':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 text-[10px] font-medium border border-amber-500/20">
            <RotateCcw size={10} /> Rolled Back
          </span>
        );
      case 'running':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 text-[10px] font-medium border border-blue-500/20 animate-pulse">
            <Clock size={10} /> Running
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 text-[10px] font-mono">
            Pending
          </span>
        );
    }
  };

  return (
    <div className={`space-y-3 ${compact ? '' : 'mt-3 pt-3 border-t border-slate-800'}`}>
      {/* Header */}
      <div className="flex items-center justify-between text-xs text-indigo-400 font-semibold">
        <div className="flex items-center gap-1.5">
          <ListChecks size={15} />
          <span>Execution Plan {planStructure?.goal ? `— ${planStructure.goal}` : ''}</span>
        </div>
        {hasNodes && (
          <div className="flex items-center gap-1 text-[10px] font-mono text-slate-400">
            <GitBranch size={12} />
            <span>{planStructure?.nodes?.length} nodes</span>
          </div>
        )}
      </div>

      {/* Structured DAG Nodes View */}
      {hasNodes ? (
        <div className="space-y-2">
          {planStructure?.nodes?.map((node, idx) => (
            <div
              key={node.id || idx}
              className="bg-slate-950/80 p-2.5 rounded-xl border border-slate-800/80 space-y-1.5"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-indigo-400 text-xs min-w-[20px]">
                    {idx + 1}.
                  </span>
                  <span className="font-mono text-xs font-medium text-slate-200">{node.tool_name}</span>
                </div>
                {renderStatusBadge(node.status)}
              </div>

              {node.description && (
                <p className="text-xs text-slate-300 pl-7 leading-relaxed">{node.description}</p>
              )}

              {node.depends_on && node.depends_on.length > 0 && (
                <div className="pl-7 flex items-center gap-1.5 text-[10px] font-mono text-slate-400">
                  <span>Depends on:</span>
                  {node.depends_on.map((dep) => (
                    <span key={dep} className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-300">
                      {dep}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        /* Sequential steps list fallback */
        <ol className="space-y-1.5 text-xs">
          {planSteps?.map((step, idx) => (
            <li key={idx} className="flex items-start gap-2 bg-slate-950/60 p-2.5 rounded-xl border border-slate-800/80">
              <span className="font-mono font-bold text-indigo-400 text-xs min-w-[20px] mt-0.5">
                {idx + 1}.
              </span>
              <span className="text-slate-300 leading-relaxed">{step}</span>
            </li>
          ))}
        </ol>
      )}

      {/* Action Button */}
      {onExecutePlan && (
        <button
          type="button"
          disabled={isLoading}
          onClick={() => {
            const summary = planSteps?.join('; ') || planStructure?.nodes?.map((n) => n.tool_name).join('; ') || '';
            onExecutePlan(`Esegui il piano per: ${summary}`);
          }}
          className="mt-2 inline-flex items-center gap-1.5 px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-all shadow-md shadow-indigo-600/20 cursor-pointer active:scale-95"
        >
          <Play size={13} className="fill-current" />
          <span>Avvia Esecuzione Piano</span>
        </button>
      )}
    </div>
  );
};
