import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CitationItem, Message } from '../types';
import { getDocumentFileUrl } from '../services/api';
import { formatBytes } from './UploadChips';
import {
  Bot,
  User,
  AlertTriangle,
  FileText,
  Image as ImageIcon,
  FileCode,
  Zap,
  Bookmark,
  ExternalLink,
  X,
} from 'lucide-react';

interface MessageItemProps {
  message: Message;
}

export const CitationChip: React.FC<{
  citation: CitationItem;
  onClickImage?: (url: string, title: string) => void;
}> = ({ citation, onClickImage }) => {
  const isImage = /\.(png|jpe?g|webp|gif)$/i.test(citation.filename);
  const fileUrl = getDocumentFileUrl(citation.document_id);
  const targetUrl = citation.page ? `${fileUrl}#page=${citation.page}` : fileUrl;

  const handleClick = (e: React.MouseEvent) => {
    if (isImage && onClickImage) {
      e.preventDefault();
      onClickImage(fileUrl, citation.filename);
    }
  };

  return (
    <a
      href={targetUrl}
      target="_blank"
      rel="noopener noreferrer"
      onClick={handleClick}
      className="inline-flex items-center space-x-1 px-1.5 py-0.5 mx-0.5 rounded-md bg-indigo-50/90 hover:bg-indigo-100 text-indigo-700 hover:text-indigo-900 border border-indigo-200 text-[11px] font-medium no-underline shadow-2xs transition-colors cursor-pointer"
      title={`Open ${citation.filename}${citation.page ? ` (page ${citation.page})` : ''}`}
    >
      {isImage ? (
        <ImageIcon className="w-3 h-3 text-indigo-500 flex-shrink-0" />
      ) : citation.page ? (
        <FileText className="w-3 h-3 text-rose-500 flex-shrink-0" />
      ) : (
        <FileCode className="w-3 h-3 text-slate-500 flex-shrink-0" />
      )}
      <span className="truncate max-w-[120px]">{citation.filename}</span>
      {citation.page && (
        <span className="font-semibold text-indigo-800">· p.{citation.page}</span>
      )}
    </a>
  );
};

export const MessageItem: React.FC<MessageItemProps> = ({ message }) => {
  const isUser = message.role === 'user';
  const isInterrupted = message.meta?.interrupted;
  const citations = message.meta?.citations || [];
  const usage = message.meta?.usage;
  const attachedDocs = message.meta?.attached_documents || [];

  const [lightbox, setLightbox] = useState<{ url: string; title: string } | null>(null);

  // Convert [[cite: filename.ext | p.X]] and [[cite: filename.ext]] into markdown links
  const formatContentWithCitations = (content: string): string => {
    if (!content) return '';
    return content.replace(
      /\[\[cite:\s*([^\|\]]+?)(?:\s*\|\s*p\.?\s*(\d+))?\s*\]\]/gi,
      (_, filename, page) => {
        const cleanName = filename.trim();
        const matched = citations.find(
          (c) => c.filename.toLowerCase() === cleanName.toLowerCase()
        );
        const docId = matched ? matched.document_id : '';
        const pageParam = page ? `&page=${page}` : '';
        const pageLabel = page ? ` · p.${page}` : '';
        return `[📄 ${cleanName}${pageLabel}](cite://${docId}?file=${encodeURIComponent(cleanName)}${pageParam})`;
      }
    );
  };

  const formattedContent = isUser ? message.content : formatContentWithCitations(message.content);

  return (
    <>
      <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} py-2`}>
        <div
          className={`flex max-w-[84%] items-start space-x-3 ${
            isUser ? 'flex-row-reverse space-x-reverse' : 'flex-row'
          }`}
        >
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
            {/* Attached Documents placed above user message text */}
            {isUser && attachedDocs.length > 0 && (
              <div className="mb-2.5 space-y-1.5">
                {attachedDocs.map((doc) => {
                  const isPdf = doc.mime_type === 'application/pdf';
                  const isImg = doc.mime_type.startsWith('image/');
                  const fileUrl = getDocumentFileUrl(doc.id);

                  return (
                    <a
                      key={doc.id}
                      href={fileUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => {
                        if (isImg) {
                          e.preventDefault();
                          setLightbox({ url: fileUrl, title: doc.filename });
                        }
                      }}
                      className="flex items-center space-x-2.5 px-3 py-2 rounded-xl bg-white/15 hover:bg-white/25 border border-white/20 text-white shadow-2xs transition-all no-underline cursor-pointer group"
                      title={`View ${doc.filename}`}
                    >
                      <div className="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center flex-shrink-0 overflow-hidden">
                        {isImg ? (
                          <img
                            src={fileUrl}
                            alt={doc.filename}
                            className="w-8 h-8 object-cover"
                          />
                        ) : isPdf ? (
                          <FileText className="w-4 h-4 text-rose-200" />
                        ) : (
                          <FileCode className="w-4 h-4 text-indigo-100" />
                        )}
                      </div>
                      <div className="flex flex-col min-w-0 flex-1 text-left">
                        <span className="font-semibold text-xs truncate max-w-[220px]" title={doc.filename}>
                          {doc.filename}
                        </span>
                        <div className="flex items-center space-x-2 text-[10px] text-indigo-100/80">
                          {doc.size_bytes !== undefined && <span>{formatBytes(doc.size_bytes)}</span>}
                          {doc.page_count ? <span>· {doc.page_count} pages</span> : null}
                          {doc.mode && (
                            <span className="uppercase text-[9px] px-1 py-0.2 rounded bg-white/20 font-bold tracking-wide">
                              {doc.mode}
                            </span>
                          )}
                        </div>
                      </div>
                      <ExternalLink className="w-3.5 h-3.5 text-white/60 group-hover:text-white flex-shrink-0" />
                    </a>
                  );
                })}
              </div>
            )}

            {isUser ? (
              <div className="whitespace-pre-wrap leading-relaxed">{message.content}</div>
            ) : (
              <div className="prose-chat text-slate-800">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    a: ({ href, children }) => {
                      if (href?.startsWith('cite://')) {
                        try {
                          const urlObj = new URL(href);
                          const docId = urlObj.hostname;
                          const fileName = urlObj.searchParams.get('file') || 'Document';
                          const pageStr = urlObj.searchParams.get('page');
                          const page = pageStr ? parseInt(pageStr, 10) : null;

                          const citeObj: CitationItem = {
                            document_id: docId,
                            filename: fileName,
                            page,
                            marker_text: `[[cite: ${fileName}${page ? ` | p.${page}` : ''}]]`,
                          };

                          return (
                            <CitationChip
                              citation={citeObj}
                              onClickImage={(url, title) => setLightbox({ url, title })}
                            />
                          );
                        } catch {
                          return <span>{children}</span>;
                        }
                      }

                      return (
                        <a href={href} target="_blank" rel="noopener noreferrer">
                          {children}
                        </a>
                      );
                    },
                  }}
                >
                  {formattedContent}
                </ReactMarkdown>
              </div>
            )}

            {/* Grouped Citations Footer Bar */}
            {!isUser && citations.length > 0 && (
              <div className="mt-3 pt-2.5 border-t border-slate-100 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                <span className="font-medium text-[11px] text-slate-400 mr-1 flex items-center space-x-1">
                  <Bookmark className="w-3 h-3 text-indigo-500" />
                  <span>Sources:</span>
                </span>
                {citations.map((cite, i) => (
                  <CitationChip
                    key={i}
                    citation={cite}
                    onClickImage={(url, title) => setLightbox({ url, title })}
                  />
                ))}
              </div>
            )}

            {/* Token Usage Badge */}
            {!isUser && usage && (
              <div className="mt-2 flex items-center space-x-1.5 text-[10px] text-slate-400">
                <Zap className="w-3 h-3 text-amber-500" />
                <span>
                  {usage.prompt_tokens?.toLocaleString()} prompt · {usage.candidates_tokens?.toLocaleString()} output
                  {usage.total_tokens ? ` (${usage.total_tokens.toLocaleString()} total tokens)` : ''}
                </span>
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

      {/* Lightbox Modal for Images */}
      {lightbox && (
        <div
          className="fixed inset-0 z-50 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in"
          onClick={() => setLightbox(null)}
        >
          <div
            className="relative max-w-4xl max-h-[90vh] bg-white rounded-2xl overflow-hidden shadow-2xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between bg-slate-50">
              <span className="font-semibold text-sm text-slate-800 truncate">{lightbox.title}</span>
              <div className="flex items-center space-x-2">
                <a
                  href={lightbox.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="p-1 text-slate-400 hover:text-indigo-600 rounded transition-colors"
                  title="Open original in new tab"
                >
                  <ExternalLink className="w-4 h-4" />
                </a>
                <button
                  onClick={() => setLightbox(null)}
                  className="p-1 text-slate-400 hover:text-slate-600 rounded transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
            <div className="p-2 flex items-center justify-center overflow-auto max-h-[80vh] bg-slate-900/5">
              <img src={lightbox.url} alt={lightbox.title} className="max-w-full max-h-[75vh] object-contain rounded-lg" />
            </div>
          </div>
        </div>
      )}
    </>
  );
};
