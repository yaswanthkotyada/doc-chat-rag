import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Message } from '../types';
import { Bot, User, AlertTriangle } from 'lucide-react';

interface MessageItemProps {
  message: Message;
}

export const MessageItem: React.FC<MessageItemProps> = ({ message }) => {
  const isUser = message.role === 'user';
  const isInterrupted = message.meta?.interrupted;

  return (
    <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} py-2`}>
      <div className={`flex max-w-[82%] items-start space-x-3 ${isUser ? 'flex-row-reverse space-x-reverse' : 'flex-row'}`}>
        {/* Avatar */}
        <div
          className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold ${
            isUser ? 'bg-indigo-600 text-white' : 'bg-slate-200 text-slate-700'
          }`}
        >
          {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4 text-indigo-600" />}
        </div>

        {/* Message Bubble */}
        <div
          className={`rounded-2xl px-4 py-3 text-sm shadow-sm ${
            isUser
              ? 'bg-indigo-600 text-white rounded-tr-none'
              : 'bg-white border border-slate-200 text-slate-800 rounded-tl-none'
          }`}
        >
          {isUser ? (
            <div className="whitespace-pre-wrap leading-relaxed">{message.content}</div>
          ) : (
            <div className="prose-chat text-slate-800">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}

          {isInterrupted && (
            <div className="mt-2 flex items-center space-x-1 text-xs text-amber-600 bg-amber-50 px-2 py-1 rounded border border-amber-200">
              <AlertTriangle className="w-3.5 h-3.5" />
              <span>Generation stopped mid-stream</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

