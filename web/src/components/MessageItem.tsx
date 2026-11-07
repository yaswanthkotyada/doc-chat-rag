import React, { useState, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CitationItem, Message, AgentStepTrace, ChunkDetailResponse } from '../types';
import { getDocumentFileUrl, fetchChunkDetail } from '../services/api';
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
  X,
  ChevronDown,
  ChevronRight,
  Layers,
  CheckCircle2,
  Compass,
} from 'lucide-react';

interface MessageItemProps {
  message: Message;
}

// Module-level cache for chunk previews to avoid repeated network calls
const chunkPreviewCache = new Map<string, ChunkDetailResponse>();

export const CitationChip: React.FC<{
  citation: CitationItem;
  onClickImage?: (url: string, title: string) => void;
}> = ({ citation, onClickImage }) => {
  const isImage = /\.(png|jpe?g|webp|gif)$/i.test(citation.filename);
  const fileUrl = getDocumentFileUrl(citation.document_id);
  const targetUrl = citation.page ? `${fileUrl}#page=${citation.page}` : fileUrl;

  const [previewOpen, setPreviewOpen] = useState(false);
  const [chunkDetail, setChunkDetail] = useState<ChunkDetailResponse | null>(null);
  const [loadingChunk, setLoadingChunk] = useState(false);
  const timeoutRef = useRef<any>(null);

  const pageLabel = citation.page_end && citation.page && citation.page_end !== citation.page
    ? `p.${citation.page}-${citation.page_end}`
    : citation.page
    ? `p.${citation.page}`
    : null;

  const handleMouseEnter = () => {
    if (!citation.chunk_id) return;
    timeoutRef.current = setTimeout(async () => {
      setPreviewOpen(true);
      if (chunkPreviewCache.has(citation.chunk_id!)) {
        setChunkDetail(chunkPreviewCache.get(citation.chunk_id!)!);
      } else {
        setLoadingChunk(true);
        try {
          const detail = await fetchChunkDetail(citation.chunk_id!);
          chunkPreviewCache.set(citation.chunk_id!, detail);
          setChunkDetail(detail);
        } catch {
          // Ignore fetch error
        } finally {
          setLoadingChunk(false);
        }
      }
    }, 250);
  };

  const handleMouseLeave = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setPreviewOpen(false);
  };

  const handleClick = (e: React.MouseEvent) => {
    if (isImage && onClickImage) {
      e.preventDefault();
      onClickImage(fileUrl, citation.filename);
    }
  };

  return (
    <span
      className="relative inline-block"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <a
        href={targetUrl}
        target="_blank"
        rel="noopener noreferrer"
        onClick={handleClick}
        className="inline-flex items-center space-x-1 px-1.5 py-0.5 mx-0.5 rounded-md bg-indigo-50/90 hover:bg-indigo-100 text-indigo-700 hover:text-indigo-900 border border-indigo-200 text-[11px] font-medium no-underline shadow-2xs transition-colors cursor-pointer"
        title={`Open ${citation.filename}${pageLabel ? ` (${pageLabel})` : ''}`}
      >
        {isImage ? (
          <ImageIcon className="w-3 h-3 text-indigo-500 flex-shrink-0" />
        ) : citation.page ? (
          <FileText className="w-3 h-3 text-rose-500 flex-shrink-0" />
        ) : (
          <FileCode className="w-3 h-3 text-slate-500 flex-shrink-0" />
        )}
        <span className="truncate max-w-[120px]">{citation.filename}</span>
        {pageLabel && (
          <span className="font-semibold text-indigo-800">· {pageLabel}</span>
        )}
      </a>

      {/* Citation Chunk Hover Preview Popover */}
      {previewOpen && citation.chunk_id && (
        <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-1.5 w-80 p-3 bg-white rounded-lg shadow-xl border border-slate-200 text-left text-xs pointer-events-auto">
          <div className="flex items-center justify-between pb-1.5 border-b border-slate-100 mb-2">
            <span className="font-semibold text-slate-800 truncate max-w-[190px]">
              {citation.filename}
            </span>
            {pageLabel && (
              <span className="text-[10px] font-bold text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">
                {pageLabel}
              </span>
            )}
          </div>

          {loadingChunk ? (
            <div className="py-3 text-center text-slate-400 text-[11px] animate-pulse">
              Loading chunk preview...
            </div>
          ) : chunkDetail ? (
            <div className="space-y-1.5">
              {chunkDetail.chunk.heading_path && chunkDetail.chunk.heading_path.length > 0 && (
                <div className="text-[10px] text-slate-500 font-medium truncate">
                  {chunkDetail.chunk.heading_path.join(' > ')}
                </div>
              )}
              <div className="p-2 rounded bg-slate-50 text-[11px] text-slate-700 line-clamp-5 whitespace-pre-wrap font-sans border border-slate-100 italic">
                "{chunkDetail.chunk.text.slice(0, 320)}
                {chunkDetail.chunk.text.length > 320 ? '...' : ''}"
              </div>
              <div className="flex items-center justify-between text-[9px] text-slate-400 pt-1">
                <span>Chunk #{chunkDetail.chunk.chunk_index} · {chunkDetail.chunk.token_count} tokens</span>
                <span className="text-emerald-600 font-medium flex items-center space-x-0.5">
                  <CheckCircle2 className="w-2.5 h-2.5" />
                  <span>Grounding Source</span>
                </span>
              </div>
            </div>
          ) : (
            <div className="py-2 text-center text-slate-400 text-[11px]">
              Chunk text unavailable.
            </div>
          )}
        </div>
      )}
    </span>
  );
};

export const SearchTracePanel: React.FC<{
  agentTrace: AgentStepTrace[];
  limitHit?: boolean;
  totalSteps?: number;
  totalToolCalls?: number;
}> = ({ agentTrace, limitHit, totalSteps, totalToolCalls }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!agentTrace || agentTrace.length === 0) return null;

  // Extract unique pages explored across all searches
  const allPages = Array.from(new Set(agentTrace.flatMap((t) => t.pages || []))).sort((a, b) => a - b);
  const totalDuration = agentTrace.reduce((acc, t) => acc + (t.duration_ms || 0), 0);

  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50/70 overflow-hidden text-xs">
      {/* Header bar */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-3 py-2 flex items-center justify-between bg-slate-100/70 hover:bg-slate-100 text-slate-700 transition-colors text-left cursor-pointer"
      >
        <div className="flex items-center space-x-2">
          <Compass className="w-3.5 h-3.5 text-indigo-600 flex-shrink-0" />
          <span className="font-semibold text-slate-800 text-[11px]">How I found this:</span>
          <span className="text-[10px] text-slate-500">
            {totalToolCalls !== undefined ? `${totalToolCalls} search(es)` : `${agentTrace.length} search step(s)`}
            {totalSteps ? ` across ${totalSteps} turns` : ''}
          </span>
          {allPages.length > 0 && (
            <span className="text-[10px] bg-white border border-slate-200 text-slate-600 px-1.5 py-0.5 rounded font-mono">
              pp. {allPages.slice(0, 6).join(', ')}{allPages.length > 6 ? '...' : ''}
            </span>
          )}
        </div>

        <div className="flex items-center space-x-2">
          {limitHit && (
            <span
              className="text-[10px] font-semibold text-amber-700 bg-amber-100 border border-amber-200 px-1.5 py-0.2 rounded"
              title="Search step limit reached; answer synthesized from retrieved passages"
            >
              Search Cap Reached
            </span>
          )}
          <span className="text-[10px] text-slate-400 font-mono">
            {Math.round(totalDuration)}ms
          </span>
          {isOpen ? (
            <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
          )}
        </div>
      </button>

      {/* Expanded Step Details */}
      {isOpen && (
        <div className="p-3 space-y-2 border-t border-slate-200/80 bg-white">
          {agentTrace.map((trace, idx) => {
            const queryArg = trace.arguments?.query;
            const resIdArg = trace.arguments?.result_id;

            return (
              <div
                key={idx}
                className="p-2 rounded-md bg-slate-50 border border-slate-100 flex items-start justify-between text-[11px]"
              >
                <div className="space-y-0.5">
                  <div className="flex items-center space-x-1.5">
                    <span className="font-bold text-slate-400 text-[10px]">#{trace.step}</span>
                    <span className="font-semibold text-indigo-700 font-mono text-[10px]">
                      {trace.tool}
                    </span>
                    {queryArg && (
                      <span className="text-slate-800 font-medium">
                        "{queryArg}"
                      </span>
                    )}
                    {resIdArg && (
                      <span className="text-slate-800 font-medium">
                        target: {resIdArg}
                      </span>
                    )}
                  </div>
                  {trace.pages && trace.pages.length > 0 && (
                    <div className="text-[10px] text-slate-500">
                      Pages covered: <span className="font-mono text-slate-700">{trace.pages.join(', ')}</span>
                    </div>
                  )}
                </div>

                <div className="text-right text-[10px] text-slate-500 flex-shrink-0 ml-3">
                  <span className="font-semibold text-slate-700">
                    {trace.result_count} passage{trace.result_count !== 1 ? 's' : ''}
                  </span>
                  <div className="text-slate-400 font-mono">{trace.duration_ms}ms</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export const MessageItem: React.FC<MessageItemProps> = ({ message }) => {
  const isUser = message.role === 'user';
  const isInterrupted = message.meta?.interrupted;
  const citations = message.meta?.citations || [];
  const usage = message.meta?.usage;
  const attachedDocs = message.meta?.attached_documents || [];
  const agentTrace = message.meta?.agent_trace || [];
  const routingPlan = message.meta?.routing_plan;
  const limitHit = message.meta?.limit_hit;

  const [lightbox, setLightbox] = useState<{ url: string; title: string } | null>(null);

  // Convert [[cite: filename.ext | p.X]] and [[cite: filename.ext | p.X-Y]] into markdown links
  const formatContentWithCitations = (content: string): string => {
    if (!content) return '';
    return content.replace(
      /\[\[cite:\s*([^\|\]]+?)(?:\s*\|\s*p\.?\s*([\d\-]+))?\s*\]\]/gi,
      (_, filename, pageRange) => {
        const cleanName = filename.trim();
        const matched = citations.find(
          (c) => c.filename.toLowerCase() === cleanName.toLowerCase()
        );
        const docId = matched ? matched.document_id : '';
        const chunkId = matched?.chunk_id ? `&chunk=${matched.chunk_id}` : '';
        const pageParam = pageRange ? `&page=${pageRange}` : '';
        const pageLabel = pageRange ? ` · p.${pageRange}` : '';
        return `[📄 ${cleanName}${pageLabel}](cite://${docId}?file=${encodeURIComponent(cleanName)}${pageParam}${chunkId})`;
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
            className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 text-white shadow-2xs ${
              isUser
                ? 'bg-gradient-to-tr from-indigo-600 to-indigo-500'
                : 'bg-gradient-to-tr from-slate-700 to-slate-900 border border-slate-600'
            }`}
          >
            {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4 text-indigo-300" />}
          </div>

          {/* Bubble */}
          <div
            className={`flex flex-col rounded-2xl px-4 py-3 shadow-xs transition-all ${
              isUser
                ? 'bg-indigo-600 text-white rounded-tr-xs'
                : 'bg-white border border-slate-200 text-slate-800 rounded-tl-xs'
            }`}
          >
            {/* Attached Documents Header for User Turn */}
            {isUser && attachedDocs.length > 0 && (
              <div className="mb-2 pb-2 border-b border-indigo-500/40 flex flex-wrap gap-1.5">
                {attachedDocs.map((doc, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[11px] font-medium bg-indigo-700/80 text-indigo-100"
                    title={`${doc.filename} (${formatBytes(doc.size_bytes || 0)})`}
                  >
                    <FileText className="w-3 h-3 text-indigo-300 flex-shrink-0" />
                    <span className="truncate max-w-[130px]">{doc.filename}</span>
                    {doc.mode && (
                      <span className="text-[9px] px-1 py-0.2 bg-indigo-800 text-indigo-200 rounded uppercase font-bold">
                        {doc.mode}
                      </span>
                    )}
                  </span>
                ))}
              </div>
            )}

            {/* Routing Mode Badge for Assistant Message */}
            {!isUser && routingPlan && routingPlan.mode !== 'none' && (
              <div className="mb-1.5 flex items-center space-x-1.5">
                <span
                  className={`inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider ${
                    routingPlan.mode === 'rag'
                      ? 'bg-purple-100 text-purple-800 border border-purple-200'
                      : routingPlan.mode === 'mixed'
                      ? 'bg-indigo-100 text-indigo-800 border border-indigo-200'
                      : 'bg-blue-100 text-blue-800 border border-blue-200'
                  }`}
                  title={routingPlan.summary}
                >
                  <Layers className="w-2.5 h-2.5" />
                  <span>{routingPlan.mode} MODE</span>
                </span>
              </div>
            )}

            {/* Message Body */}
            {isUser ? (
              <div className="text-sm font-normal leading-relaxed whitespace-pre-wrap break-words">
                {message.content}
              </div>
            ) : (
              <div className="text-sm font-normal leading-relaxed prose prose-slate prose-sm max-w-none break-words">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    a: ({ href, children }) => {
                      if (href?.startsWith('cite://')) {
                        try {
                          const url = new URL(href);
                          const docId = url.hostname;
                          const fileName = decodeURIComponent(url.searchParams.get('file') || '');
                          const pageRange = url.searchParams.get('page');
                          const chunkId = url.searchParams.get('chunk');

                          const page = pageRange ? parseInt(pageRange.split('-')[0], 10) : undefined;
                          const pageEnd = pageRange && pageRange.includes('-')
                            ? parseInt(pageRange.split('-')[1], 10)
                            : page;

                          const citeObj: CitationItem = {
                            document_id: docId,
                            filename: fileName,
                            page,
                            page_end: pageEnd,
                            chunk_id: chunkId,
                            marker_text: `[[cite: ${fileName}${pageRange ? ` | p.${pageRange}` : ''}]]`,
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

            {/* Collapsible Search Execution Trace Panel */}
            {!isUser && agentTrace.length > 0 && (
              <SearchTracePanel
                agentTrace={agentTrace}
                limitHit={limitHit}
                totalSteps={message.meta?.total_steps}
                totalToolCalls={message.meta?.total_tool_calls}
              />
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
                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                <span>Response generation was stopped.</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Image Lightbox Modal */}
      {lightbox && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-4"
          onClick={() => setLightbox(null)}
        >
          <div
            className="relative max-w-4xl max-h-[90vh] bg-slate-900 rounded-xl overflow-hidden shadow-2xl p-2 flex flex-col items-center"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-full flex items-center justify-between pb-2 px-2 text-white border-b border-slate-700">
              <span className="text-sm font-semibold truncate max-w-md">{lightbox.title}</span>
              <button
                onClick={() => setLightbox(null)}
                className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="overflow-auto max-h-[80vh] p-2 flex items-center justify-center">
              <img
                src={lightbox.url}
                alt={lightbox.title}
                className="max-w-full max-h-[75vh] object-contain rounded"
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
};
