import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github-dark.css';
import { Copy, Check, ExternalLink } from 'lucide-react';

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content, className = '' }) => {
  return (
    <div className={`markdown-body space-y-2 text-slate-100 ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          // Styled headings
          h1: ({ children }) => (
            <h1 className="text-base sm:text-lg font-bold text-slate-100 mt-3 mb-2 pb-1 border-b border-slate-800">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-sm sm:text-base font-semibold text-slate-200 mt-2.5 mb-1.5 pb-0.5 border-b border-slate-800/60">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-xs sm:text-sm font-semibold text-blue-300 mt-2 mb-1">
              {children}
            </h3>
          ),
          
          // Styled Paragraphs
          p: ({ children }) => (
            <p className="leading-relaxed text-xs sm:text-sm text-slate-200 mb-2 font-sans">
              {children}
            </p>
          ),

          // Styled Unordered & Ordered Lists
          ul: ({ children }) => (
            <ul className="list-disc list-inside space-y-1 my-2 text-xs sm:text-sm text-slate-300 pl-1">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal list-inside space-y-1 my-2 text-xs sm:text-sm text-slate-300 pl-1">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li className="leading-normal">{children}</li>
          ),

          // Styled Blockquotes
          blockquote: ({ children }) => (
            <blockquote className="border-l-3 border-blue-500 bg-slate-900/80 px-3 py-1.5 my-2 rounded-r-lg text-xs sm:text-sm text-slate-300 italic">
              {children}
            </blockquote>
          ),

          // Styled Hyperlinks
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-blue-400 hover:text-blue-300 underline underline-offset-2 transition font-medium"
            >
              <span>{children}</span>
              <ExternalLink size={11} className="inline shrink-0" />
            </a>
          ),

          // Styled GFM Tables
          table: ({ children }) => (
            <div className="overflow-x-auto my-3 rounded-xl border border-slate-800 shadow-sm bg-slate-950/80">
              <table className="w-full text-left text-xs border-collapse font-sans">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-slate-900/90 text-slate-200 font-semibold border-b border-slate-800 uppercase text-[10px] tracking-wider">
              {children}
            </thead>
          ),
          tbody: ({ children }) => (
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {children}
            </tbody>
          ),
          tr: ({ children }) => (
            <tr className="hover:bg-slate-900/40 transition-colors">
              {children}
            </tr>
          ),
          th: ({ children }) => (
            <th className="px-3 py-2 font-mono font-medium text-blue-300">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-3 py-2 font-mono text-[11px] sm:text-xs leading-relaxed">
              {children}
            </td>
          ),

          // Custom Code Blocks (Inline vs Fenced with Copy Button)
          code: ({ node, className, children, ...props }) => {
            const match = /language-(\w+)/.exec(className || '');
            const codeString = String(children).replace(/\n$/, '');

            if (!match && !codeString.includes('\n')) {
              // Inline code snippet
              return (
                <code
                  className="bg-slate-900 border border-slate-800 text-cyan-300 px-1.5 py-0.5 rounded font-mono text-[11px] sm:text-xs"
                  {...props}
                >
                  {children}
                </code>
              );
            }

            return <CodeBlock language={match ? match[1] : ''} code={codeString} />;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

// Helper Sub-component for Fenced Code Blocks with Copy Button
const CodeBlock: React.FC<{ language: string; code: string }> = ({ language, code }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="my-3 rounded-xl border border-slate-800 bg-slate-950 overflow-hidden shadow-sm font-mono text-xs">
      {/* Header bar */}
      <div className="bg-slate-900/90 border-b border-slate-800/80 px-3 py-1.5 flex items-center justify-between text-slate-400">
        <span className="text-[10px] font-semibold uppercase text-cyan-400 tracking-wider">
          {language || 'code'}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-slate-200 transition bg-slate-800/60 hover:bg-slate-800 px-2 py-0.5 rounded border border-slate-700/60 cursor-pointer"
          title="Copy code to clipboard"
        >
          {copied ? (
            <>
              <Check size={11} className="text-emerald-400" />
              <span className="text-emerald-400 font-medium">Copied!</span>
            </>
          ) : (
            <>
              <Copy size={11} />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code Body — highlighted da rehype-highlight (hljs classes) */}
      <pre className="p-3 overflow-x-auto text-slate-200 leading-relaxed font-mono text-[11px] sm:text-xs whitespace-pre hljs bg-slate-950">
        <code className={`hljs ${language ? `language-${language}` : ''}`}>{code}</code>
      </pre>
    </div>
  );
};
