import React, { useState } from 'react';
import { Settings as SettingsIcon, KeyRound, X, Save, CheckCircle2 } from 'lucide-react';
import { getApiKey, setApiKey } from '../api';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const [apiKey, setLocalApiKey] = useState(getApiKey());
  const [saved, setSaved] = useState(false);

  if (!isOpen) return null;

  const handleSave = () => {
    setApiKey(apiKey);
    setSaved(true);
    setTimeout(() => {
      setSaved(false);
      onClose();
    }, 800);
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      {/* Backdrop */}
      <div onClick={onClose} className="absolute inset-0 bg-slate-950/80 backdrop-blur-sm" />

      {/* Modal */}
      <div className="relative bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-md p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-slate-200">
            <SettingsIcon size={16} className="text-blue-400" />
            <span className="font-semibold text-sm">Impostazioni</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-500 hover:text-white hover:bg-slate-800 rounded transition"
          >
            <X size={16} />
          </button>
        </div>

        {/* API Key */}
        <div className="space-y-1.5">
          <label className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
            <KeyRound size={12} className="text-amber-400" />
            API Key (header X-API-Key)
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setLocalApiKey(e.target.value)}
            placeholder="Inserisci la chiave API del backend..."
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500/60"
          />
          <p className="text-[10px] text-slate-600 leading-snug">
            Salvata in localStorage e inviata automaticamente a tutte le chiamate API.
          </p>
        </div>

        {/* Save */}
        <button
          onClick={handleSave}
          className={`w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition cursor-pointer ${
            saved
              ? 'bg-emerald-600/30 border border-emerald-500/50 text-emerald-300'
              : 'bg-blue-600 hover:bg-blue-500 text-white'
          }`}
        >
          {saved ? (
            <>
              <CheckCircle2 size={13} />
              Salvato!
            </>
          ) : (
            <>
              <Save size={13} />
              Salva impostazioni
            </>
          )}
        </button>
      </div>
    </div>
  );
};
