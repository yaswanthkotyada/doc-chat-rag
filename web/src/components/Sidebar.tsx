import React from 'react';
import { Conversation, HealthStatus } from '../types';
import { MessageSquarePlus, Trash2, Cpu } from 'lucide-react';

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onDelete: (id: string, e: React.MouseEvent) => void;
  health: HealthStatus | null;
  healthLoading: boolean;
  onRefreshHealth: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  conversations,
  activeId,
  onSelect,
  onNewChat,
  onDelete,
  health,
  healthLoading,
  onRefreshHealth,
}) => {
  return (
    <aside className="w-72 bg-slate-900 text-slate-100 flex flex-col h-full border-r border-slate-800">
      {/* Top Header & New Chat Button */}
      <div className="p-4 border-b border-slate-800">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
            <Cpu className="w-6 h-6 text-indigo-400" />
            <h1 className="font-semibold text-lg tracking-tight">DOC POC</h1>
          </div>
          <span className="text-xs bg-indigo-950 text-indigo-300 px-2 py-0.5 rounded-full border border-indigo-800">
            Stage 3
          </span>
        </div>

        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center space-x-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-2 px-4 rounded-lg transition-colors shadow-sm"
        >
          <MessageSquarePlus className="w-4 h-4" />
          <span>New Chat</span>
        </button>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto px-2 py-3 space-y-1">
        {conversations.length === 0 ? (
          <div className="text-center py-8 text-slate-400 text-sm">
            No conversations yet.
          </div>
        ) : (
          conversations.map((c) => {
            const isActive = c.id === activeId;
            return (
              <div
                key={c.id}
                onClick={() => onSelect(c.id)}
                className={`group relative flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer text-sm transition-colors ${
                  isActive
                    ? 'bg-slate-800 text-white font-medium'
                    : 'text-slate-300 hover:bg-slate-800/60 hover:text-white'
                }`}
              >
                <div className="truncate pr-6">
                  {c.title || 'Untitled Conversation'}
                </div>

                <button
                  onClick={(e) => onDelete(c.id, e)}
                  title="Delete conversation"
                  className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-400 p-1 rounded transition-opacity"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* Stage 1 Health Indicator Widget */}
      <div className="p-3 border-t border-slate-800 bg-slate-950/60 text-xs">
        <div className="flex items-center justify-between text-slate-400 mb-2">
          <span className="font-semibold uppercase tracking-wider text-[10px]">System Health</span>
          <button
            onClick={onRefreshHealth}
            className="text-slate-400 hover:text-slate-200 transition-colors"
            title="Refresh health"
          >
            {healthLoading ? 'checking...' : 'refresh'}
          </button>
        </div>

        {health ? (
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div className="flex items-center space-x-1.5">
              <span className={`w-2 h-2 rounded-full ${health.api === 'ok' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
              <span className="text-slate-300">API: {health.api}</span>
            </div>

            <div className="flex items-center space-x-1.5">
              <span className={`w-2 h-2 rounded-full ${health.db === 'ok' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
              <span className="text-slate-300">DB: {health.db}</span>
            </div>

            <div className="flex items-center space-x-1.5">
              <span className={`w-2 h-2 rounded-full ${health.pgvector === 'ok' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
              <span className="text-slate-300">pgvector: {health.pgvector}</span>
            </div>

            <div className="flex items-center space-x-1.5">
              <span className={`w-2 h-2 rounded-full ${health.gemini_key_configured ? 'bg-emerald-500' : 'bg-amber-500'}`} />
              <span className="text-slate-300">Gemini: {health.gemini_key_configured ? 'Ready' : 'Missing Key'}</span>
            </div>
          </div>
        ) : (
          <div className="text-slate-500 text-center py-1">Connecting to backend...</div>
        )}
      </div>
    </aside>
  );
};

