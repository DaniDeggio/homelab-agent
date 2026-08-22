import React, { useCallback, useEffect, useRef, useState } from 'react';
import { BookOpen, Upload, Trash2, Search, FileText, RefreshCw, Loader2 } from 'lucide-react';
import {
  listKbDocuments,
  uploadKbDocument,
  deleteKbDocument,
  searchKb,
  type KbDocument,
  type KbSearchResult,
} from '../api';

type Tab = 'docs' | 'search';

export const KnowledgePanel: React.FC = () => {
  const [tab, setTab] = useState<Tab>('docs');
  const [docs, setDocs] = useState<KbDocument[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);

  // Search state
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<KbSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      setDocs(await listKbDocuments());
    } catch {
      setDocs([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleFileUpload = async (file: File) => {
    if (!file) return;
    const validExt = ['.md', '.txt', '.pdf'];
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    if (!validExt.includes(ext)) {
      setUploadMsg(`Formato non supportato: ${ext}. Usa .md, .txt o .pdf`);
      setTimeout(() => setUploadMsg(null), 4000);
      return;
    }
    setIsUploading(true);
    setUploadMsg(null);
    try {
      let content: string;
      if (ext === '.pdf') {
        // Per i PDF inviamo il binario via FormData-like: usiamo base64 semplificato
        // Il backend accetta multipart; qui convertiamo in testo se possibile
        setUploadMsg('PDF: usa il testo estratto o converti in .md/.txt per ora');
        setTimeout(() => setUploadMsg(null), 5000);
        return;
      }
      content = await file.text();
      const res = await uploadKbDocument(file.name, content);
      setUploadMsg(`✓ ${file.name}: ${res.chunks_indexed} chunk indicizzati`);
      await refresh();
    } catch (e: any) {
      setUploadMsg(`Errore: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setIsUploading(false);
      setTimeout(() => setUploadMsg(null), 5000);
    }
  };

  const handleDelete = async (filename: string) => {
    try {
      await deleteKbDocument(filename);
      await refresh();
    } catch (e: any) {
      console.error('Delete failed', e);
    }
  };

  const handleSearch = async () => {
    if (!query.trim()) return;
    setIsSearching(true);
    try {
      setResults(await searchKb(query.trim(), 5));
    } catch {
      setResults([]);
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="bg-slate-950 border border-slate-800 rounded-xl p-3.5 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-slate-400 text-xs">
          <BookOpen size={14} className="text-cyan-400" />
          <span className="font-medium text-slate-300">Knowledge Base</span>
        </div>
        <button onClick={refresh} className="p-1 text-slate-500 hover:text-slate-300 transition rounded" title="Refresh">
          <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-900 rounded-lg p-0.5">
        <button
          onClick={() => setTab('docs')}
          className={`flex-1 px-2 py-1 rounded-md text-[10px] font-semibold transition ${
            tab === 'docs' ? 'bg-slate-800 text-slate-200' : 'text-slate-500 hover:text-slate-300'
          }`}
        >
          Documents ({docs.length})
        </button>
        <button
          onClick={() => setTab('search')}
          className={`flex-1 px-2 py-1 rounded-md text-[10px] font-semibold transition ${
            tab === 'search' ? 'bg-slate-800 text-slate-200' : 'text-slate-500 hover:text-slate-300'
          }`}
        >
          Search
        </button>
      </div>

      {tab === 'docs' ? (
        <div className="space-y-2">
          {/* Upload */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".md,.txt,.pdf"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg border border-dashed border-slate-700 text-[10px] text-slate-400 hover:border-cyan-500/50 hover:text-cyan-300 transition disabled:opacity-50 cursor-pointer"
          >
            {isUploading ? <Loader2 size={11} className="animate-spin" /> : <Upload size={11} />}
            Upload .md / .txt / .pdf
          </button>
          {uploadMsg && <p className="text-[10px] text-slate-400 italic">{uploadMsg}</p>}

          {/* Document list */}
          {docs.length === 0 && !isLoading && (
            <p className="text-xs text-slate-500 italic">No documents indexed yet.</p>
          )}
          {docs.map((doc) => (
            <div
              key={doc.filename}
              className="flex items-center justify-between gap-2 bg-slate-900/60 border border-slate-800 rounded-lg px-2.5 py-1.5 group"
            >
              <div className="min-w-0 flex-1 flex items-center gap-1.5">
                <FileText size={12} className="text-cyan-400 shrink-0" />
                <span className="text-[11px] font-mono text-slate-300 truncate">{doc.filename}</span>
                <span className="text-[9px] text-slate-600 shrink-0">{doc.chunks}ch</span>
              </div>
              <button
                onClick={() => handleDelete(doc.filename)}
                className="opacity-0 group-hover:opacity-100 p-1 text-slate-600 hover:text-red-400 transition"
                title="Delete document"
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {/* Search bar */}
          <div className="flex gap-1.5">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="Cerca nei documenti..."
              className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-2 py-1.5 text-[11px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50"
            />
            <button
              onClick={handleSearch}
              disabled={isSearching || !query.trim()}
              className="px-2 py-1.5 rounded-lg bg-cyan-600/20 border border-cyan-500/40 text-cyan-300 hover:bg-cyan-600/40 transition disabled:opacity-50 cursor-pointer"
            >
              {isSearching ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
            </button>
          </div>

          {/* Results */}
          {results.map((r) => (
            <div key={r.filename} className="bg-slate-900/60 border border-slate-800 rounded-lg p-2 space-y-1">
              <div className="flex items-center gap-1.5 text-[10px] font-mono text-cyan-300">
                <FileText size={10} />
                {r.filename}
              </div>
              {r.chunks.slice(0, 2).map((c, i) => (
                <div key={i} className="text-[10px] text-slate-400 leading-snug line-clamp-3">
                  <span className="text-emerald-500 font-mono mr-1">{(c.score * 100).toFixed(0)}%</span>
                  {c.content.slice(0, 150)}...
                </div>
              ))}
            </div>
          ))}
          {results.length === 0 && !isSearching && query && (
            <p className="text-xs text-slate-500 italic">Nessun risultato.</p>
          )}
        </div>
      )}
    </div>
  );
};
