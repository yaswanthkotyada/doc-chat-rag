import React, { useEffect, useState, useMemo } from 'react';
import { ChunkDetailResponse, ChunkItem, DocumentIndexResponse, DocumentItem } from '../types';
import { fetchChunkDetail, fetchDocumentChunks, fetchDocumentIndex, triggerDocumentIndex } from '../services/api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  X,
  Layers,
  Table as TableIcon,
  FileText,
  Search,
  ChevronRight,
  RefreshCw,
  Loader2,
  AlertCircle,
  CheckCircle2,
  ArrowLeft,
  ArrowRight,
} from 'lucide-react';

interface ChunksViewModalProps {
  document: DocumentItem | null;
  isOpen: boolean;
  onClose: () => void;
  onIndexed?: () => void;
}

export const ChunksViewModal: React.FC<ChunksViewModalProps> = ({
  document,
  isOpen,
  onClose,
  onIndexed,
}) => {
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [indexInfo, setIndexInfo] = useState<DocumentIndexResponse | null>(null);
  const [selectedChunkId, setSelectedChunkId] = useState<string | null>(null);
  const [selectedNeighbours, setSelectedNeighbours] = useState<ChunkDetailResponse | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [loading, setLoading] = useState(false);
  const [loadingNeighbours, setLoadingNeighbours] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewTab, setViewTab] = useState<'content' | 'embed_text' | 'neighbours'>('content');

  const loadData = async () => {
    if (!document) return;
    setLoading(true);
    setError(null);
    try {
      const [chunksRes, indexRes] = await Promise.all([
        fetchDocumentChunks(document.id),
        fetchDocumentIndex(document.id).catch(() => null),
      ]);
      setChunks(chunksRes.chunks);
      setIndexInfo(indexRes);
      if (chunksRes.chunks.length > 0 && !selectedChunkId) {
        setSelectedChunkId(chunksRes.chunks[0].id);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load chunks');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen && document) {
      loadData();
    } else {
      setChunks([]);
      setSelectedChunkId(null);
      setSelectedNeighbours(null);
      setSearchQuery('');
    }
  }, [isOpen, document?.id]);

  // Load neighbours when selected chunk changes
  useEffect(() => {
    if (!selectedChunkId) {
      setSelectedNeighbours(null);
      return;
    }
    setLoadingNeighbours(true);
    fetchChunkDetail(selectedChunkId)
      .then((detail) => setSelectedNeighbours(detail))
      .catch((err) => console.error('Failed to fetch neighbours:', err))
      .finally(() => setLoadingNeighbours(false));
  }, [selectedChunkId]);

  const handleReindex = async () => {
    if (!document) return;
    setReindexing(true);
    try {
      await triggerDocumentIndex(document.id, true);
      // Wait a moment and refresh
      setTimeout(async () => {
        await loadData();
        setReindexing(false);
        if (onIndexed) onIndexed();
      }, 2000);
    } catch (err: any) {
      setError(err.message || 'Failed to trigger re-index');
      setReindexing(false);
    }
  };

  const filteredChunks = useMemo(() => {
    return chunks.filter((c) => {
      if (typeFilter !== 'all' && c.chunk_type !== typeFilter) return false;
      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      const inText = c.text.toLowerCase().includes(q);
      const inHeading = c.heading_path.some((h) => h.toLowerCase().includes(q));
      const inIndex = String(c.chunk_index) === q;
      return inText || inHeading || inIndex;
    });
  }, [chunks, typeFilter, searchQuery]);

  const selectedChunk = useMemo(() => {
    return chunks.find((c) => c.id === selectedChunkId) || chunks[0] || null;
  }, [chunks, selectedChunkId]);

  if (!isOpen || !document) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 sm:p-6 animate-in fade-in">
      <div className="bg-white w-full max-w-6xl h-[90vh] rounded-2xl shadow-2xl flex flex-col overflow-hidden border border-slate-200">
        {/* Header */}
        <header className="h-16 px-6 border-b border-slate-200 bg-slate-50 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center space-x-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-indigo-100 text-indigo-700 flex items-center justify-center flex-shrink-0">
              <Layers className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center space-x-2">
                <h2 className="text-base font-bold text-slate-800 truncate" title={document.filename}>
                  {document.filename}
                </h2>
                <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-indigo-100 text-indigo-700">
                  {chunks.length} chunks
                </span>
                {indexInfo?.index_status === 'indexed' && (
                  <span className="inline-flex items-center space-x-1 text-xs px-2 py-0.5 rounded-full font-medium bg-emerald-100 text-emerald-800">
                    <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                    <span>Indexed</span>
                  </span>
                )}
                {indexInfo?.index_status === 'indexing' && (
                  <span className="inline-flex items-center space-x-1 text-xs px-2 py-0.5 rounded-full font-medium bg-blue-100 text-blue-800">
                    <Loader2 className="w-3 h-3 animate-spin text-blue-600" />
                    <span>Embedding chunks...</span>
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-500 flex items-center space-x-3 mt-0.5">
                <span>Model: {indexInfo?.embedding_model || 'gemini-embedding-001'}</span>
                <span>•</span>
                <span>Dimensions: {indexInfo?.embedding_dimension || 768}</span>
                {indexInfo?.indexed_at && (
                  <>
                    <span>•</span>
                    <span>Indexed: {new Date(indexInfo.indexed_at).toLocaleTimeString()}</span>
                  </>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <button
              onClick={handleReindex}
              disabled={reindexing || loading}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border border-slate-300 bg-white hover:bg-slate-100 text-slate-700 text-xs font-semibold shadow-2xs transition-all disabled:opacity-50 cursor-pointer"
              title="Re-run chunking and vector indexing"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${reindexing ? 'animate-spin text-indigo-600' : ''}`} />
              <span>{reindexing ? 'Re-indexing...' : 'Re-index'}</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-200/60 transition-colors"
              title="Close modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </header>

        {/* Content Body */}
        {loading ? (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-400">
            <Loader2 className="w-8 h-8 animate-spin text-indigo-600 mb-2" />
            <p className="text-sm">Loading chunks...</p>
          </div>
        ) : error ? (
          <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
            <AlertCircle className="w-10 h-10 text-rose-500 mb-3" />
            <h3 className="text-base font-semibold text-slate-800 mb-1">Failed to Load Chunks</h3>
            <p className="text-sm text-slate-500 max-w-md mb-4">{error}</p>
            <button
              onClick={loadData}
              className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-semibold hover:bg-indigo-700 transition-colors"
            >
              Retry
            </button>
          </div>
        ) : chunks.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center p-6 text-center text-slate-400">
            <Layers className="w-12 h-12 text-slate-300 mb-3" />
            <h3 className="text-base font-semibold text-slate-700 mb-1">No Chunks Found</h3>
            <p className="text-sm text-slate-500 max-w-md mb-4">
              This document has not been chunked or indexed yet. Ensure it is parsed, then click "Re-index".
            </p>
            <button
              onClick={handleReindex}
              disabled={reindexing}
              className="flex items-center space-x-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-semibold hover:bg-indigo-700 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${reindexing ? 'animate-spin' : ''}`} />
              <span>Trigger Chunking & Indexing</span>
            </button>
          </div>
        ) : (
          <div className="flex-1 flex overflow-hidden">
            {/* Left Column: Chunks Master List */}
            <div className="w-2/5 border-r border-slate-200 flex flex-col bg-slate-50/50">
              {/* Search & Filter Bar */}
              <div className="p-3 border-b border-slate-200 space-y-2 bg-white">
                <div className="relative">
                  <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                  <input
                    type="text"
                    placeholder="Search chunk text, heading, or #..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-9 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:bg-white"
                  />
                  {searchQuery && (
                    <button
                      onClick={() => setSearchQuery('')}
                      className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-600 text-xs"
                    >
                      ×
                    </button>
                  )}
                </div>

                <div className="flex items-center space-x-1 text-xs">
                  <span className="text-slate-400 text-[11px] mr-1">Type:</span>
                  {(['all', 'text', 'table', 'list'] as const).map((t) => (
                    <button
                      key={t}
                      onClick={() => setTypeFilter(t)}
                      className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                        typeFilter === t
                          ? 'bg-indigo-600 text-white'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                      }`}
                    >
                      {t === 'all' ? 'All' : t.charAt(0).toUpperCase() + t.slice(1)}
                    </button>
                  ))}
                  <span className="ml-auto text-[11px] text-slate-400">
                    {filteredChunks.length} of {chunks.length}
                  </span>
                </div>
              </div>

              {/* Scrollable List */}
              <div className="flex-1 overflow-y-auto p-3 space-y-2">
                {filteredChunks.map((chunk) => {
                  const isSelected = chunk.id === selectedChunk?.id;
                  const isTable = chunk.chunk_type === 'table';

                  return (
                    <div
                      key={chunk.id}
                      onClick={() => setSelectedChunkId(chunk.id)}
                      className={`p-3 rounded-xl border text-left cursor-pointer transition-all ${
                        isSelected
                          ? 'bg-indigo-50/80 border-indigo-500 shadow-xs'
                          : isTable
                          ? 'bg-amber-50/40 border-amber-200 hover:border-amber-300'
                          : 'bg-white border-slate-200 hover:border-slate-300 hover:bg-slate-50/80'
                      }`}
                    >
                      {/* Top Badges */}
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center space-x-1.5">
                          <span
                            className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              isSelected
                                ? 'bg-indigo-600 text-white'
                                : 'bg-slate-200 text-slate-700'
                            }`}
                          >
                            #{chunk.chunk_index}
                          </span>
                          {isTable ? (
                            <span className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800 border border-amber-200">
                              <TableIcon className="w-2.5 h-2.5" />
                              <span>Table</span>
                            </span>
                          ) : (
                            <span className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-600">
                              <FileText className="w-2.5 h-2.5" />
                              <span>{chunk.chunk_type}</span>
                            </span>
                          )}
                        </div>

                        <div className="flex items-center space-x-2 text-[11px] text-slate-500">
                          <span>
                            {chunk.page_start === chunk.page_end
                              ? `p. ${chunk.page_start}`
                              : `p. ${chunk.page_start}–${chunk.page_end}`}
                          </span>
                          <span>•</span>
                          <span>{chunk.token_count} tok</span>
                        </div>
                      </div>

                      {/* Heading Breadcrumb */}
                      {chunk.heading_path && chunk.heading_path.length > 0 && (
                        <div className="flex items-center text-[10px] text-indigo-700 font-semibold mb-1 truncate">
                          {chunk.heading_path.join(' › ')}
                        </div>
                      )}

                      {/* Snippet Preview */}
                      <p className="text-xs text-slate-600 line-clamp-2 leading-relaxed">
                        {chunk.text.slice(0, 140)}...
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Right Column: Chunk Detail & Inspector */}
            <div className="w-3/5 flex flex-col bg-white">
              {selectedChunk ? (
                <>
                  {/* Detail Header / Tabs */}
                  <div className="p-4 border-b border-slate-200 bg-white flex items-center justify-between flex-shrink-0">
                    <div className="flex items-center space-x-2">
                      <span className="px-2 py-0.5 rounded-md font-bold text-xs bg-indigo-600 text-white">
                        Chunk #{selectedChunk.chunk_index}
                      </span>
                      {selectedChunk.chunk_type === 'table' && (
                        <span className="px-2 py-0.5 rounded-md font-semibold text-xs bg-amber-100 text-amber-800 border border-amber-200 flex items-center space-x-1">
                          <TableIcon className="w-3 h-3" />
                          <span>Table Chunk</span>
                        </span>
                      )}
                      <span className="text-xs text-slate-500">
                        {selectedChunk.page_start === selectedChunk.page_end
                          ? `Page ${selectedChunk.page_start}`
                          : `Pages ${selectedChunk.page_start}–${selectedChunk.page_end}`}
                      </span>
                      <span className="text-xs text-slate-400">•</span>
                      <span className="text-xs text-slate-500 font-medium">
                        {selectedChunk.token_count} tokens (~{selectedChunk.text.length} chars)
                      </span>
                    </div>

                    {/* View Tabs */}
                    <div className="flex items-center space-x-1 bg-slate-100 p-0.5 rounded-lg text-xs">
                      <button
                        onClick={() => setViewTab('content')}
                        className={`px-3 py-1 rounded-md font-medium transition-colors ${
                          viewTab === 'content'
                            ? 'bg-white text-indigo-600 shadow-2xs font-semibold'
                            : 'text-slate-600 hover:text-slate-900'
                        }`}
                      >
                        Content Text
                      </button>
                      <button
                        onClick={() => setViewTab('embed_text')}
                        className={`px-3 py-1 rounded-md font-medium transition-colors ${
                          viewTab === 'embed_text'
                            ? 'bg-white text-indigo-600 shadow-2xs font-semibold'
                            : 'text-slate-600 hover:text-slate-900'
                        }`}
                        title="Text sent to the Gemini embedding API (includes document & heading prefix)"
                      >
                        Embed Prefix Text
                      </button>
                      <button
                        onClick={() => setViewTab('neighbours')}
                        className={`px-3 py-1 rounded-md font-medium transition-colors ${
                          viewTab === 'neighbours'
                            ? 'bg-white text-indigo-600 shadow-2xs font-semibold'
                            : 'text-slate-600 hover:text-slate-900'
                        }`}
                        title="Inspect previous and next adjacent chunks"
                      >
                        Neighbours ({selectedNeighbours?.prev_chunk ? 'Prev' : ''}
                        {selectedNeighbours?.prev_chunk && selectedNeighbours?.next_chunk ? ' & ' : ''}
                        {selectedNeighbours?.next_chunk ? 'Next' : ''})
                      </button>
                    </div>
                  </div>

                  {/* Heading Breadcrumb Full */}
                  {selectedChunk.heading_path && selectedChunk.heading_path.length > 0 && (
                    <div className="px-6 py-2 bg-indigo-50/50 border-b border-indigo-100 flex items-center space-x-1.5 text-xs text-indigo-800 font-semibold overflow-x-auto">
                      <span className="text-slate-400">Path:</span>
                      {selectedChunk.heading_path.map((h, i) => (
                        <React.Fragment key={i}>
                          {i > 0 && <ChevronRight className="w-3.5 h-3.5 text-indigo-400" />}
                          <span className="bg-indigo-100/70 px-2 py-0.5 rounded text-indigo-900">
                            {h}
                          </span>
                        </React.Fragment>
                      ))}
                    </div>
                  )}

                  {/* Tab Body */}
                  <div className="flex-1 overflow-y-auto p-6">
                    {viewTab === 'content' && (
                      <div className="space-y-4">
                        {selectedChunk.chunk_type === 'table' ? (
                          <div className="p-4 rounded-xl bg-amber-50/60 border border-amber-200">
                            <div className="flex items-center space-x-2 text-xs font-semibold text-amber-800 mb-2">
                              <TableIcon className="w-4 h-4 text-amber-600" />
                              <span>Table Chunk Preview (Markdown Table Format)</span>
                            </div>
                            <div className="overflow-x-auto prose prose-sm max-w-none prose-table:border prose-table:border-amber-200 prose-th:bg-amber-100/80 prose-th:p-2 prose-td:p-2">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                {selectedChunk.text}
                              </ReactMarkdown>
                            </div>
                          </div>
                        ) : (
                          <div className="prose prose-slate max-w-none text-sm text-slate-800 leading-relaxed font-sans bg-slate-50 p-5 rounded-xl border border-slate-200">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {selectedChunk.text}
                            </ReactMarkdown>
                          </div>
                        )}

                        <div className="pt-4 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
                          <div>
                            <span className="font-semibold text-slate-700">Chunk ID: </span>
                            <span className="font-mono text-[11px]">{selectedChunk.id}</span>
                          </div>
                          <div>
                            <span className="font-semibold text-slate-700">Tokens: </span>
                            <span>{selectedChunk.token_count}</span>
                          </div>
                        </div>
                      </div>
                    )}

                    {viewTab === 'embed_text' && (
                      <div className="space-y-3">
                        <div className="p-3 bg-blue-50 border border-blue-200 rounded-xl text-xs text-blue-800">
                          <p className="font-semibold mb-1">What is Embed Text?</p>
                          <p>
                            This is the exact string passed to the Gemini embedding model (task type: RETRIEVAL_DOCUMENT).
                            It includes document title and hierarchical heading breadcrumbs as context prefixes to boost semantic search relevance.
                          </p>
                        </div>
                        <pre className="p-4 bg-slate-900 text-emerald-400 font-mono text-xs rounded-xl overflow-x-auto whitespace-pre-wrap leading-relaxed shadow-inner">
                          {selectedChunk.embed_text}
                        </pre>
                      </div>
                    )}

                    {viewTab === 'neighbours' && (
                      <div className="space-y-6">
                        {loadingNeighbours ? (
                          <div className="flex items-center justify-center py-12 text-slate-400">
                            <Loader2 className="w-6 h-6 animate-spin text-indigo-600 mr-2" />
                            <span className="text-sm">Loading neighbours...</span>
                          </div>
                        ) : (
                          <>
                            {/* Previous Chunk */}
                            <div className="p-4 rounded-xl border border-slate-200 bg-slate-50/70">
                              <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center space-x-2">
                                  <ArrowLeft className="w-4 h-4 text-slate-500" />
                                  <span className="text-xs font-bold text-slate-700">
                                    Previous Chunk {selectedNeighbours?.prev_chunk ? `(#${selectedNeighbours.prev_chunk.chunk_index})` : '(None - Start of Document)'}
                                  </span>
                                </div>
                                {selectedNeighbours?.prev_chunk && (
                                  <button
                                    onClick={() => setSelectedChunkId(selectedNeighbours.prev_chunk!.id)}
                                    className="text-xs text-indigo-600 hover:text-indigo-800 font-semibold flex items-center space-x-1"
                                  >
                                    <span>Jump to Chunk</span>
                                    <ChevronRight className="w-3.5 h-3.5" />
                                  </button>
                                )}
                              </div>
                              {selectedNeighbours?.prev_chunk ? (
                                <p className="text-xs text-slate-600 line-clamp-3 bg-white p-3 rounded-lg border border-slate-200">
                                  {selectedNeighbours.prev_chunk.text}
                                </p>
                              ) : (
                                <p className="text-xs text-slate-400 italic">No preceding chunk.</p>
                              )}
                            </div>

                            {/* Current Selected Chunk */}
                            <div className="p-4 rounded-xl border-2 border-indigo-500 bg-indigo-50/30">
                              <div className="flex items-center justify-between mb-2">
                                <span className="text-xs font-bold text-indigo-900">
                                  Current Chunk (#{selectedChunk.chunk_index})
                                </span>
                                <span className="text-xs text-indigo-700 font-medium">
                                  {selectedChunk.token_count} tokens
                                </span>
                              </div>
                              <p className="text-xs text-slate-800 bg-white p-3 rounded-lg border border-indigo-200">
                                {selectedChunk.text}
                              </p>
                            </div>

                            {/* Next Chunk */}
                            <div className="p-4 rounded-xl border border-slate-200 bg-slate-50/70">
                              <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center space-x-2">
                                  <ArrowRight className="w-4 h-4 text-slate-500" />
                                  <span className="text-xs font-bold text-slate-700">
                                    Next Chunk {selectedNeighbours?.next_chunk ? `(#${selectedNeighbours.next_chunk.chunk_index})` : '(None - End of Document)'}
                                  </span>
                                </div>
                                {selectedNeighbours?.next_chunk && (
                                  <button
                                    onClick={() => setSelectedChunkId(selectedNeighbours.next_chunk!.id)}
                                    className="text-xs text-indigo-600 hover:text-indigo-800 font-semibold flex items-center space-x-1"
                                  >
                                    <span>Jump to Chunk</span>
                                    <ChevronRight className="w-3.5 h-3.5" />
                                  </button>
                                )}
                              </div>
                              {selectedNeighbours?.next_chunk ? (
                                <p className="text-xs text-slate-600 line-clamp-3 bg-white p-3 rounded-lg border border-slate-200">
                                  {selectedNeighbours.next_chunk.text}
                                </p>
                              ) : (
                                <p className="text-xs text-slate-400 italic">No subsequent chunk.</p>
                              )}
                            </div>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">
                  Select a chunk on the left to inspect its content and neighbours.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
