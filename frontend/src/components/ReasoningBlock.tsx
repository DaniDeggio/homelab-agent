import React, { useRef, useEffect, useState } from 'react';
import { Lightbulb, ChevronDown } from 'lucide-react';
import { MarkdownRenderer } from './MarkdownRenderer';

interface ReasoningBlockProps {
  content: string;
  isStreaming?: boolean;
}

const ReasoningBlock: React.FC<ReasoningBlockProps> = ({ content, isStreaming }) => {
  const contentRef = useRef<HTMLDivElement>(null);
  const [userHasScrolled, setUserHasScrolled] = useState(false);
  const [isOpen, setIsOpen] = useState(false);

  // Auto-scroll logic
  useEffect(() => {
    if (!isOpen || !isStreaming || !contentRef.current) return;
    
    const node = contentRef.current;
    
    const scrollObserver = new MutationObserver(() => {
      if (!userHasScrolled) {
        requestAnimationFrame(() => {
          if (node) {
            node.scrollTo({
              top: node.scrollHeight,
              behavior: 'smooth'
            });
          }
        });
      }
    });

    scrollObserver.observe(node, { childList: true, subtree: true, characterData: true });

    return () => scrollObserver.disconnect();
  }, [isOpen, isStreaming, userHasScrolled]);

  // Handle manual scroll to disable auto-scroll
  const handleScroll = () => {
    if (!contentRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = contentRef.current;
    const isAtBottom = Math.abs(scrollHeight - clientHeight - scrollTop) < 10;
    setUserHasScrolled(!isAtBottom);
  };

  // Open automatically when streaming starts
  useEffect(() => {
    if (isStreaming && content.length > 0 && !isOpen) {
      setIsOpen(true);
    }
  }, [isStreaming, content.length]);

  if (!content) return null;

  return (
    <details 
      className="mb-3 bg-slate-900/60 border border-slate-700/60 rounded-xl overflow-hidden [&_summary::-webkit-details-marker]:hidden group transition-all duration-200 shadow-sm"
      open={isOpen}
      onToggle={(e) => setIsOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary className="px-3.5 py-2.5 cursor-pointer flex items-center justify-between text-xs text-slate-400 font-medium hover:bg-slate-800/80 hover:text-slate-300 transition-colors select-none">
        <div className="flex items-center gap-2.5">
          <Lightbulb size={14} className="text-amber-500/90 animate-pulse" />
          <span>{isStreaming ? 'Thinking...' : 'Reasoning Process'}</span>
        </div>
        <ChevronDown size={14} className="group-open:rotate-180 transition-transform duration-300 ease-in-out opacity-70" />
      </summary>
      <div 
        ref={contentRef}
        onScroll={handleScroll}
        className="px-4 py-3 text-slate-300/90 border-t border-slate-700/60 bg-slate-950/40 text-sm leading-relaxed max-h-[300px] overflow-y-auto custom-scrollbar"
      >
        <MarkdownRenderer content={content} />
      </div>
    </details>
  );
};

export default ReasoningBlock;
