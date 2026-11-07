import React, { useState } from 'react';
import { DocumentItem } from '../types';
import { getDocumentFileUrl } from '../services/api';
import { formatBytes } from './UploadChips';
import {
  FileText,
  Image as ImageIcon,
  ExternalLink,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Loader2,
  X,
  FileCode,
  Eye,
  Clock,
  RefreshCw,
  Layers,
  ArrowLeftRight,
} from 'lucide-react';

interface DocumentsDrawerProps {
  documents: DocumentItem[];
  isOpen: boolean;
  onClose: () => void;
  onDeleteDocument: (docId: string) => void;
  onViewParsed?: (doc: DocumentItem) => void;
  onRetryParse?: (docId: string) => void;
  onViewChunks?: (doc: DocumentItem) => void;
  onRetryIndex?: (docId: string) => void;
  onUpdateModeOverride?: (docId: string, override: 'direct' | 'rag' | null) => Promise<void>;
}

export const DocumentsDrawer: React.FC<DocumentsDrawerProps> = ({
  documents,
  isOpen,
  onClose,
  onDeleteDocument,
  onViewParsed,
  onRetryParse,
  onViewChunks,
  onRetryIndex,
  onUpdateModeOverride,
}) => {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleDeleteClick = (docId: string) => {
    if (confirmDeleteId === docId) {
      onDeleteDocument(docId);
      setConfirmDeleteId(null);
    } else {
      setConfirmDeleteId(docId);
    }
  };

  return (
    <aside className="w-84 border-l border-slate-200 bg-white flex flex-col h-full shadow-lg z-20 transition-all">
      {/* Drawer Header */}
      <div className="h-14 px-4 border-b border-slate-200 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <FileText className="w-5 h-5 text-indigo-600" />
          <h3 className="font-semibold text-slate-800 text-sm">Conversation Documents</h3>
          <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-medium">
            {documents.length}
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-600 p-1 rounded-lg"
          title="Close panel"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Documents List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {documents.length === 0 ? (
          <div className="text-center py-16 text-slate-400 text-sm">
            <FileText className="w-8 h-8 mx-auto mb-2 text-slate-300" />
            <p>No documents attached yet.</p>
            <p className="text-xs text-slate-400 mt-1">Upload PDFs, images, or text files using the paperclip or drag-and-drop.</p>
          </div>
        ) : (
          documents.map((doc) => {
            const isImage = doc.mime_type.startsWith('image/');
            const isPdf = doc.mime_type === 'application/pdf';
            const fileUrl = getDocumentFileUrl(doc.id);

            const isParsing = doc.parse_status === 'parsing';
            const isParsed = doc.parse_status === 'parsed';
            const isParseFailed = doc.parse_status === 'failed';
            const isParsePending = doc.parse_status === 'pending';
            const isParseSkipped = doc.parse_status === 'skipped';

            return (
              <div
                key={doc.id}
                className="p-3 border border-slate-200 rounded-xl hover:border-slate-300 transition-all bg-slate-50/50"
              >
                <div className="flex items-start justify-between">
                  {/* File Thumbnail or Icon */}
                  <div className="flex items-start space-x-2.5 min-w-0 flex-1">
                    {isImage && doc.status === 'ready' ? (
                      <a href={fileUrl} target="_blank" rel="noopener noreferrer" className="flex-shrink-0">
                        <img
                          src={fileUrl}
                          alt={doc.filename}
                          className="w-10 h-10 rounded-lg object-cover border border-slate-200 hover:opacity-90 transition-opacity"
                        />
                      </a>
                    ) : isPdf ? (
                      <div className="w-10 h-10 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center flex-shrink-0">
                        <FileText className="w-5 h-5" />
                      </div>
                    ) : isImage ? (
                      <div className="w-10 h-10 rounded-lg bg-indigo-100 text-indigo-600 flex items-center justify-center flex-shrink-0">
                        <ImageIcon className="w-5 h-5" />
                      </div>
                    ) : (
                      <div className="w-10 h-10 rounded-lg bg-slate-200 text-slate-600 flex items-center justify-center flex-shrink-0">
                        <FileCode className="w-5 h-5" />
                      </div>
                    )}

                    {/* Metadata */}
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold text-slate-800 truncate" title={doc.filename}>
                        {doc.filename}
                      </div>

                      <div className="text-[11px] text-slate-500 mt-0.5 flex flex-wrap gap-x-2">
                        <span>{formatBytes(doc.size_bytes)}</span>
                        {doc.page_count && <span>• {doc.page_count} pages</span>}
                        {doc.width && doc.height && <span>• {doc.width}×{doc.height}</span>}
                        {doc.meta?.lines && <span>• {doc.meta.lines} lines</span>}
                      </div>

                      {/* Status & Mode */}
                      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                        {doc.status === 'ready' && (
                          <span className="flex items-center text-emerald-600 space-x-1">
                            <CheckCircle2 className="w-3 h-3" />
                            <span>Ready</span>
                          </span>
                        )}

                        {/* Effective Mode Badge */}
                        {doc.mode_override ? (
                          <span
                            className={`px-1.5 py-0.2 rounded font-semibold text-[10px] ${
                              doc.mode_override === 'rag'
                                ? 'bg-purple-100 text-purple-800 border border-purple-200'
                                : 'bg-blue-100 text-blue-800 border border-blue-200'
                            }`}
                            title={`Mode manually forced to ${doc.mode_override.toUpperCase()}`}
                          >
                            {doc.mode_override.toUpperCase()} (Override)
                          </span>
                        ) : doc.mode === 'rag' ? (
                          <span
                            className="bg-purple-100 text-purple-700 px-1.5 py-0.2 rounded font-semibold text-[10px]"
                            title={
                              doc.index_status === 'indexed'
                                ? 'Indexed and searchable in RAG chat'
                                : 'Large document; will be searched via RAG once indexed'
                            }
                          >
                            {doc.index_status === 'indexed' ? 'RAG (Indexed)' : 'RAG (Large)'}
                          </span>
                        ) : (
                          <span className="bg-emerald-100 text-emerald-700 px-1.5 py-0.2 rounded font-semibold text-[10px]">
                            Direct
                          </span>
                        )}

                        {/* Mode Override Controls */}
                        {onUpdateModeOverride && (
                          <>
                            {doc.mode_override ? (
                              <button
                                onClick={() => onUpdateModeOverride(doc.id, null)}
                                className="text-[10px] text-slate-500 hover:text-indigo-600 hover:underline flex items-center space-x-0.5 cursor-pointer ml-1"
                                title="Reset mode to default automatic assignment"
                              >
                                <ArrowLeftRight className="w-2.5 h-2.5" />
                                <span>Reset Auto</span>
                              </button>
                            ) : doc.mode === 'direct' && doc.index_status === 'indexed' ? (
                              <button
                                onClick={() => onUpdateModeOverride(doc.id, 'rag')}
                                className="text-[10px] text-purple-600 hover:text-purple-800 hover:underline flex items-center space-x-0.5 cursor-pointer ml-1"
                                title="Force this document to use RAG tool search"
                              >
                                <ArrowLeftRight className="w-2.5 h-2.5" />
                                <span>Force RAG</span>
                              </button>
                            ) : doc.mode === 'rag' ? (
                              (doc.page_count == null || doc.page_count <= 40) && doc.size_bytes <= 20 * 1024 * 1024 ? (
                                <button
                                  onClick={() => onUpdateModeOverride(doc.id, 'direct')}
                                  className="text-[10px] text-blue-600 hover:text-blue-800 hover:underline flex items-center space-x-0.5 cursor-pointer ml-1"
                                  title="Force this document to use Direct mode (attached as file part)"
                                >
                                  <ArrowLeftRight className="w-2.5 h-2.5" />
                                  <span>Force Direct</span>
                                </button>
                              ) : (
                                <span
                                  className="text-[9px] text-slate-400 cursor-not-allowed ml-1"
                                  title="Cannot override to Direct: exceeds 40 pages or 20MB limit"
                                >
                                  (Direct N/A)
                                </span>
                              )
                            ) : null}
                          </>
                        )}
                        {doc.status === 'processing' && !isParsing && !isParsePending && (
                          <span className="flex items-center text-amber-600 space-x-1">
                            <Loader2 className="w-3 h-3 animate-spin" />
                            <span>Processing...</span>
                          </span>
                        )}
                        {doc.status === 'uploading' && (
                          <span className="flex items-center text-indigo-600 space-x-1">
                            <Loader2 className="w-3 h-3 animate-spin" />
                            <span>Uploading ({doc.uploadProgress || 0}%)...</span>
                          </span>
                        )}
                        {doc.status === 'failed' && !isParseFailed && (
                          <span className="flex items-center text-rose-600 space-x-1" title={doc.error || 'Failed'}>
                            <AlertCircle className="w-3 h-3 flex-shrink-0" />
                            <span className="truncate max-w-[140px]">{doc.error || 'Failed'}</span>
                          </span>
                        )}
                      </div>

                      {/* Stage 5 Parsing Status Badges & Progress */}
                      {isParsing && (
                        <div className="mt-2 space-y-1">
                          <div className="flex items-center justify-between text-[10px] text-indigo-700 font-medium">
                            <span className="flex items-center space-x-1">
                              <Loader2 className="w-3 h-3 animate-spin text-indigo-600" />
                              <span>Parsing with Docling...</span>
                            </span>
                            {doc.page_count ? (
                              <span>{doc.pages_parsed || 0}/{doc.page_count} pages</span>
                            ) : null}
                          </div>
                          {doc.page_count && doc.page_count > 0 && (
                            <div className="w-full bg-indigo-100 rounded-full h-1.5 overflow-hidden">
                              <div
                                className="bg-indigo-600 h-1.5 rounded-full transition-all duration-300"
                                style={{
                                  width: `${Math.min(100, Math.round(((doc.pages_parsed || 0) / doc.page_count) * 100))}%`,
                                }}
                              />
                            </div>
                          )}
                        </div>
                      )}

                      {isParsePending && (
                        <div className="mt-1 flex items-center space-x-1 text-[10px] text-amber-700 font-medium">
                          <Clock className="w-3 h-3 animate-pulse text-amber-500" />
                          <span>Parse queued (waiting for slot)</span>
                        </div>
                      )}

                      {isParsed && (
                        <div className="mt-1.5 flex items-center space-x-2">
                          <span
                            className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800 cursor-help"
                            title={
                              doc.parser_name
                                ? `${doc.parser_name} v${doc.parser_version || '1.38'}`
                                : 'Parsed'
                            }
                          >
                            <CheckCircle2 className="w-2.5 h-2.5 text-emerald-600" />
                            <span>Parsed</span>
                          </span>

                          {onViewParsed && (
                            <button
                              onClick={() => onViewParsed(doc)}
                              className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200 transition-colors shadow-2xs cursor-pointer"
                              title="Open side-by-side parsed view"
                            >
                              <Eye className="w-3 h-3" />
                              <span>Parsed View</span>
                            </button>
                          )}
                        </div>
                      )}

                      {isParseFailed && (
                        <div className="mt-1.5 space-y-1">
                          <div
                            className="flex items-center space-x-1 text-[10px] text-rose-600 font-medium truncate"
                            title={doc.parse_error || 'Parsing failed'}
                          >
                            <AlertCircle className="w-3 h-3 flex-shrink-0" />
                            <span className="truncate">{doc.parse_error || 'Parsing failed'}</span>
                          </div>
                          {onRetryParse && (
                            <button
                              onClick={() => onRetryParse(doc.id)}
                              className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-50 text-rose-700 hover:bg-rose-100 border border-rose-200 transition-colors"
                              title="Retry parsing"
                            >
                              <RefreshCw className="w-2.5 h-2.5" />
                              <span>Retry Parse</span>
                            </button>
                          )}
                        </div>
                      )}

                      {/* On-demand parse option for skipped PDF documents */}
                      {isPdf && isParseSkipped && onRetryParse && (
                        <div className="mt-1 flex items-center space-x-1">
                          <button
                            onClick={() => onRetryParse(doc.id)}
                            className="text-[10px] text-slate-500 hover:text-indigo-600 hover:underline flex items-center space-x-1"
                            title="Run Docling parser on this PDF"
                          >
                            <span>Run Docling Parse</span>
                          </button>
                        </div>
                      )}
                      {/* Stage 6 Chunking & Indexing Status Badges & Controls */}
                      {doc.index_status === 'indexing' && (
                        <div className="mt-1.5 flex items-center space-x-1.5 text-[10px] text-blue-700 font-medium">
                          <Loader2 className="w-3 h-3 animate-spin text-blue-600 flex-shrink-0" />
                          <span>Embedding chunks with Gemini...</span>
                        </div>
                      )}

                      {doc.index_status === 'pending' && (
                        <div className="mt-1.5 flex items-center space-x-1 text-[10px] text-amber-700 font-medium">
                          <Clock className="w-3 h-3 animate-pulse text-amber-500" />
                          <span>Indexing queued...</span>
                        </div>
                      )}

                      {doc.index_status === 'indexed' && (
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          <span
                            className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800"
                            title={`Indexed ${doc.chunks_count || ''} chunks`}
                          >
                            <CheckCircle2 className="w-2.5 h-2.5 text-emerald-600" />
                            <span>Indexed{doc.chunks_count ? ` (${doc.chunks_count} chunks)` : ''}</span>
                          </span>

                          {onViewChunks && (
                            <button
                              onClick={() => onViewChunks(doc)}
                              className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-purple-50 text-purple-700 hover:bg-purple-100 border border-purple-200 transition-colors shadow-2xs cursor-pointer"
                              title="Browse chunks and check embeddings"
                            >
                              <Layers className="w-3 h-3" />
                              <span>Chunks</span>
                            </button>
                          )}

                          {onRetryIndex && (
                            <button
                              onClick={() => onRetryIndex(doc.id)}
                              className="p-0.5 text-slate-400 hover:text-slate-600 rounded transition-colors"
                              title="Re-run indexing"
                            >
                              <RefreshCw className="w-2.5 h-2.5" />
                            </button>
                          )}
                        </div>
                      )}

                      {doc.index_status === 'failed' && (
                        <div className="mt-1.5 space-y-1">
                          <div
                            className="flex items-center space-x-1 text-[10px] text-rose-600 font-medium truncate"
                            title={doc.index_error || 'Indexing failed'}
                          >
                            <AlertCircle className="w-3 h-3 flex-shrink-0" />
                            <span className="truncate">{doc.index_error || 'Indexing failed'}</span>
                          </div>
                          {onRetryIndex && (
                            <button
                              onClick={() => onRetryIndex(doc.id)}
                              className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-50 text-rose-700 hover:bg-rose-100 border border-rose-200 transition-colors cursor-pointer"
                              title="Retry indexing"
                            >
                              <RefreshCw className="w-2.5 h-2.5" />
                              <span>Retry Index</span>
                            </button>
                          )}
                        </div>
                      )}

                      {/* On-demand Index button for parsed documents that have not been indexed yet */}
                      {isParsed && (!doc.index_status || doc.index_status === 'skipped') && onRetryIndex && (
                        <div className="mt-1 flex items-center space-x-1">
                          <button
                            onClick={() => onRetryIndex(doc.id)}
                            className="text-[10px] text-purple-600 hover:text-purple-800 hover:underline flex items-center space-x-1 cursor-pointer font-medium"
                            title="Chunk and index document for vector/keyword search"
                          >
                            <Layers className="w-2.5 h-2.5" />
                            <span>Index Chunks</span>
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center space-x-1 ml-2">
                    {doc.index_status === 'indexed' && onViewChunks && (
                      <button
                        onClick={() => onViewChunks(doc)}
                        className="p-1.5 text-slate-400 hover:text-purple-600 rounded transition-colors"
                        title="Open Chunks View"
                      >
                        <Layers className="w-3.5 h-3.5" />
                      </button>
                    )}
                    {isParsed && onViewParsed && (
                      <button
                        onClick={() => onViewParsed(doc)}
                        className="p-1.5 text-slate-400 hover:text-indigo-600 rounded transition-colors"
                        title="Open Parsed View"
                      >
                        <Eye className="w-3.5 h-3.5" />
                      </button>
                    )}
                    {doc.status === 'ready' && (
                      <a
                        href={fileUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1.5 text-slate-400 hover:text-indigo-600 rounded transition-colors"
                        title="Open file in new tab"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    )}
                    <button
                      onClick={() => handleDeleteClick(doc.id)}
                      className={`p-1.5 rounded transition-colors text-xs flex items-center space-x-1 ${confirmDeleteId === doc.id
                          ? 'bg-rose-600 text-white hover:bg-rose-700 px-2'
                          : 'text-slate-400 hover:text-rose-600'
                        }`}
                      title={confirmDeleteId === doc.id ? 'Click again to confirm delete' : 'Delete document'}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      {confirmDeleteId === doc.id && <span>Delete?</span>}
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
};
