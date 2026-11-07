import React, { useState, useEffect, useMemo } from 'react';
import { DocumentItem, SearchDebugResponse, SearchResultItem } from '../types';
import { getDocumentFileUrl, searchDebug } from '../services/api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  X,
  Search,
  Sparkles,
  Table as TableIcon,
  ExternalLink,
  ChevronRight,
  Clock,
  Layers,
  AlertCircle,
  Loader2,
  Split,
  FileCode,
} from 'lucide-react';

interface SearchDebugModalProps {
  isOpen: boolean;
  onClose: () => void;
  conversationId?: string | null;
  documents: DocumentItem[];
}

export const SearchDebugModal: React.FC<SearchDebugModalProps> = ({
  isOpen,
  onClose,
  conversationId,
  documents,
}) => {
  const [query, setQuery] = useState('');
  const [searchMode, setSearchMode] = useState<'hybrid' | 'vector' | 'keyword' | 'side-by-side'>('hybrid');
  const [topK, setTopK] = useState<number>(8);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);

  // Single mode result
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<SearchDebugResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Side-by-side results
  const [loadingSideBySide, setLoadingSideBySide] = useState(false);
  const [hybridResults, setHybridResults] = useState<SearchDebugResponse | null>(null);
  const [vectorResults, setVectorResults] = useState<SearchDebugResponse | null>(null);
  const [keywordResults, setKeywordResults] = useState<SearchDebugResponse | null>(null);

  // Filter only indexed or rag documents
  const availableDocs = useMemo(() => {
    return documents.filter((d) => d.status === 'ready' || d.parse_status === 'parsed');
  }, [documents]);

  // Set default selected docs when modal opens
  useEffect(() => {
    if (isOpen) {
      const indexedIds = availableDocs
        .filter((d) => d.index_status === 'indexed' || d.parse_status === 'parsed')
        .map((d) => d.id);
      setSelectedDocIds(indexedIds.length > 0 ? indexedIds : availableDocs.map((d) => d.id));
    }
  }, [isOpen, availableDocs]);

  const handleToggleDoc = (id: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    );
  };

  const handleSelectAllDocs = () => {
    setSelectedDocIds(availableDocs.map((d) => d.id));
  };

  const handleClearDocs = () => {
    setSelectedDocIds([]);
  };

  const executeSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    setError(null);

    const docFilter = selectedDocIds.length > 0 ? selectedDocIds : undefined;

    if (searchMode === 'side-by-side') {
      setLoadingSideBySide(true);
      try {
        const [hRes, vRes, kRes] = await Promise.all([
          searchDebug({
            query: query.trim(),
            mode: 'hybrid',
            limit: topK,
            document_ids: docFilter,
            conversation_id: conversationId || undefined,
          }),
          searchDebug({
            query: query.trim(),
            mode: 'vector',
            limit: topK,
            document_ids: docFilter,
            conversation_id: conversationId || undefined,
          }),
          searchDebug({
            query: query.trim(),
            mode: 'keyword',
            limit: topK,
            document_ids: docFilter,
            conversation_id: conversationId || undefined,
          }),
        ]);
        setHybridResults(hRes);
        setVectorResults(vRes);
        setKeywordResults(kRes);
      } catch (err: any) {
        setError(err.message || 'Side-by-side search failed');
      } finally {
        setLoadingSideBySide(false);
      }
    } else {
      setLoading(true);
      try {
        const res = await searchDebug({
          query: query.trim(),
          mode: searchMode,
          limit: topK,
          document_ids: docFilter,
          conversation_id: conversationId || undefined,
        });
        setResults(res);
      } catch (err: any) {
        setError(err.message || 'Search failed');
      } finally {
        setLoading(false);
      }
    }
  };

  // Term highlighter for query words in text snippets
  const highlightTerms = (text: string, q: string) => {
    if (!q.trim()) return text;
    const words = q
      .trim()
      .split(/\s+/)
      .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .filter((w) => w.length > 1);

    if (words.length === 0) return text;
    const regex = new RegExp(`(${words.join('|')})`, 'gi');
    const parts = text.split(regex);

    return parts.map((part, i) =>
      regex.test(part) ? (
        <mark key={i} className="bg-amber-200 text-amber-950 font-semibold px-0.5 rounded">
          {part}
        </mark>
      ) : (
        part
      )
    );
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 sm:p-6 animate-in fade-in">
      <div className="bg-white w-full max-w-7xl h-[92vh] rounded-2xl shadow-2xl flex flex-col overflow-hidden border border-slate-200">
        {/* Header */}
        <header className="h-16 px-6 border-b border-slate-200 bg-slate-50 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-purple-100 text-purple-700 flex items-center justify-center flex-shrink-0">
              <Search className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h2 className="text-base font-bold text-slate-800">Search Retrieval Studio</h2>
                <span className="text-[11px] px-2 py-0.5 rounded-full font-semibold bg-purple-100 text-purple-700">
                  Debug Screen
                </span>
              </div>
              <p className="text-xs text-slate-500">
                Evaluate vector cosine, keyword (Postgres FTS), and Reciprocal Rank Fusion on indexed chunks.
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-200/60 transition-colors"
            title="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </header>

        {/* Search Query Controls Bar */}
        <div className="p-4 border-b border-slate-200 bg-white space-y-3 flex-shrink-0">
          <form onSubmit={executeSearch} className="flex items-center space-x-2">
            <div className="relative flex-1">
              <Search className="w-5 h-5 text-slate-400 absolute left-3.5 top-3" />
              <input
                type="text"
                placeholder="Enter query to test retrieval (e.g. 'project schedule', 'revenue details', 'who is the architect?')..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full pl-11 pr-10 py-2.5 text-sm bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white transition-all shadow-2xs font-medium text-slate-800"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  className="absolute right-3 top-3 text-slate-400 hover:text-slate-600 text-sm"
                >
                  ×
                </button>
              )}
            </div>

            <button
              type="submit"
              disabled={!query.trim() || loading || loadingSideBySide}
              className="px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold shadow-xs flex items-center space-x-2 transition-all disabled:opacity-50 cursor-pointer flex-shrink-0"
            >
              {loading || loadingSideBySide ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Sparkles className="w-4 h-4" />
              )}
              <span>Search</span>
            </button>
          </form>

          {/* Mode Selector & Configuration Row */}
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs pt-1">
            {/* Mode Switcher */}
            <div className="flex items-center space-x-1 bg-slate-100 p-1 rounded-xl">
              <button
                type="button"
                onClick={() => setSearchMode('hybrid')}
                className={`px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer ${
                  searchMode === 'hybrid'
                    ? 'bg-white text-indigo-700 shadow-2xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                Hybrid (RRF)
              </button>
              <button
                type="button"
                onClick={() => setSearchMode('vector')}
                className={`px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer ${
                  searchMode === 'vector'
                    ? 'bg-white text-indigo-700 shadow-2xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                Vector (Cosine)
              </button>
              <button
                type="button"
                onClick={() => setSearchMode('keyword')}
                className={`px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer ${
                  searchMode === 'keyword'
                    ? 'bg-white text-indigo-700 shadow-2xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                Keyword (FTS)
              </button>
              <button
                type="button"
                onClick={() => setSearchMode('side-by-side')}
                className={`px-3 py-1.5 rounded-lg font-semibold transition-all flex items-center space-x-1 cursor-pointer ${
                  searchMode === 'side-by-side'
                    ? 'bg-white text-purple-700 shadow-2xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
                title="Run hybrid, vector, and keyword side-by-side to compare ranking differences"
              >
                <Split className="w-3.5 h-3.5" />
                <span>Side-by-Side (Compare All 3)</span>
              </button>
            </div>

            {/* Top-K Selector & Document Scope Dropdown */}
            <div className="flex items-center space-x-4">
              <div className="flex items-center space-x-1.5 text-slate-600">
                <span className="font-medium text-slate-500">Top K:</span>
                <select
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                  className="bg-slate-50 border border-slate-200 rounded-lg px-2 py-1 text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-indigo-500"
                >
                  <option value={3}>3 chunks</option>
                  <option value={5}>5 chunks</option>
                  <option value={8}>8 chunks (default)</option>
                  <option value={10}>10 chunks</option>
                  <option value={15}>15 chunks</option>
                  <option value={20}>20 chunks</option>
                </select>
              </div>

              {/* Document Scopes */}
              <div className="flex items-center space-x-1.5">
                <span className="font-medium text-slate-500">Documents ({selectedDocIds.length}/{availableDocs.length}):</span>
                {availableDocs.map((doc) => {
                  const isChecked = selectedDocIds.includes(doc.id);
                  return (
                    <button
                      key={doc.id}
                      type="button"
                      onClick={() => handleToggleDoc(doc.id)}
                      className={`px-2 py-0.5 rounded-md text-[11px] font-medium transition-colors border ${
                        isChecked
                          ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
                          : 'bg-white border-slate-200 text-slate-400 line-through'
                      }`}
                      title={doc.filename}
                    >
                      {doc.filename.length > 15 ? doc.filename.slice(0, 12) + '...' : doc.filename}
                    </button>
                  );
                })}
                {availableDocs.length > 1 && (
                  <button
                    type="button"
                    onClick={selectedDocIds.length === availableDocs.length ? handleClearDocs : handleSelectAllDocs}
                    className="text-[10px] text-slate-400 hover:text-slate-600 underline ml-1"
                  >
                    {selectedDocIds.length === availableDocs.length ? 'Clear' : 'All'}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Results Area */}
        <div className="flex-1 overflow-y-auto bg-slate-50 p-6">
          {error && (
            <div className="mb-4 p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 flex items-center space-x-3">
              <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0" />
              <div className="text-sm">{error}</div>
            </div>
          )}

          {searchMode === 'side-by-side' ? (
            /* Side-by-Side Compare Mode (3 Columns) */
            <div className="h-full flex flex-col">
              {loadingSideBySide ? (
                <div className="flex-1 flex flex-col items-center justify-center text-slate-400">
                  <Loader2 className="w-8 h-8 animate-spin text-purple-600 mb-2" />
                  <p className="text-sm">Running parallel vector, keyword, and hybrid search...</p>
                </div>
              ) : !hybridResults && !vectorResults && !keywordResults ? (
                <div className="flex-1 flex flex-col items-center justify-center text-slate-400 text-center py-16">
                  <Split className="w-12 h-12 text-slate-300 mb-3" />
                  <h3 className="text-base font-semibold text-slate-700 mb-1">Side-by-Side Retrieval Compare</h3>
                  <p className="text-xs text-slate-500 max-w-md">
                    Enter a query above and click "Search" to compare how Vector, Keyword, and Hybrid rank your documents side-by-side.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-4 h-full">
                  {/* Column 1: Hybrid RRF */}
                  <div className="flex flex-col bg-white rounded-xl border border-indigo-200 shadow-2xs overflow-hidden">
                    <div className="p-3 bg-indigo-50/70 border-b border-indigo-200 flex items-center justify-between">
                      <div>
                        <div className="text-xs font-bold text-indigo-900 flex items-center space-x-1.5">
                          <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
                          <span>Hybrid (RRF Fusion)</span>
                        </div>
                        <div className="text-[10px] text-indigo-600">
                          {hybridResults?.duration_ms}ms • {hybridResults?.total_results || 0} hits
                        </div>
                      </div>
                      <span className="text-[10px] bg-indigo-200/60 text-indigo-800 px-2 py-0.5 rounded-full font-semibold">
                        Best Quality
                      </span>
                    </div>
                    <div className="flex-1 overflow-y-auto p-3 space-y-3">
                      {hybridResults?.items.map((item, idx) => (
                        <ResultCard key={item.chunk_id} item={item} rank={idx + 1} query={query} highlightFn={highlightTerms} />
                      ))}
                      {hybridResults?.items.length === 0 && (
                        <p className="text-center text-xs text-slate-400 py-8">No results found.</p>
                      )}
                    </div>
                  </div>

                  {/* Column 2: Vector (Cosine) */}
                  <div className="flex flex-col bg-white rounded-xl border border-blue-200 shadow-2xs overflow-hidden">
                    <div className="p-3 bg-blue-50/70 border-b border-blue-200 flex items-center justify-between">
                      <div>
                        <div className="text-xs font-bold text-blue-900 flex items-center space-x-1.5">
                          <Layers className="w-3.5 h-3.5 text-blue-600" />
                          <span>Vector Only (Cosine)</span>
                        </div>
                        <div className="text-[10px] text-blue-600">
                          {vectorResults?.duration_ms}ms • {vectorResults?.total_results || 0} hits
                        </div>
                      </div>
                      <span className="text-[10px] bg-blue-200/60 text-blue-800 px-2 py-0.5 rounded-full font-semibold">
                        Semantic
                      </span>
                    </div>
                    <div className="flex-1 overflow-y-auto p-3 space-y-3">
                      {vectorResults?.items.map((item, idx) => (
                        <ResultCard key={item.chunk_id} item={item} rank={idx + 1} query={query} highlightFn={highlightTerms} />
                      ))}
                      {vectorResults?.items.length === 0 && (
                        <p className="text-center text-xs text-slate-400 py-8">No results found.</p>
                      )}
                    </div>
                  </div>

                  {/* Column 3: Keyword (Postgres FTS) */}
                  <div className="flex flex-col bg-white rounded-xl border border-emerald-200 shadow-2xs overflow-hidden">
                    <div className="p-3 bg-emerald-50/70 border-b border-emerald-200 flex items-center justify-between">
                      <div>
                        <div className="text-xs font-bold text-emerald-900 flex items-center space-x-1.5">
                          <FileCode className="w-3.5 h-3.5 text-emerald-600" />
                          <span>Keyword Only (Postgres FTS)</span>
                        </div>
                        <div className="text-[10px] text-emerald-600">
                          {keywordResults?.duration_ms}ms • {keywordResults?.total_results || 0} hits
                        </div>
                      </div>
                      <span className="text-[10px] bg-emerald-200/60 text-emerald-800 px-2 py-0.5 rounded-full font-semibold">
                        Exact Match
                      </span>
                    </div>
                    <div className="flex-1 overflow-y-auto p-3 space-y-3">
                      {keywordResults?.items.map((item, idx) => (
                        <ResultCard key={item.chunk_id} item={item} rank={idx + 1} query={query} highlightFn={highlightTerms} />
                      ))}
                      {keywordResults?.items.length === 0 && (
                        <p className="text-center text-xs text-slate-400 py-8">No results found.</p>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            /* Single Mode Results (Standard View) */
            <div>
              {loading ? (
                <div className="flex flex-col items-center justify-center py-20 text-slate-400">
                  <Loader2 className="w-8 h-8 animate-spin text-indigo-600 mb-2" />
                  <p className="text-sm">Retrieving top-{topK} chunks using {searchMode} mode...</p>
                </div>
              ) : !results ? (
                <div className="flex flex-col items-center justify-center py-24 text-center text-slate-400">
                  <Search className="w-12 h-12 text-slate-300 mb-3" />
                  <h3 className="text-base font-semibold text-slate-700 mb-1">Search Your Documents</h3>
                  <p className="text-xs text-slate-500 max-w-md">
                    Test the retrieval quality on your indexed chunks before Stage 7 wires the results into Gemini LLM answers.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Results Summary Bar */}
                  <div className="flex items-center justify-between text-xs text-slate-600 pb-2 border-b border-slate-200">
                    <div className="flex items-center space-x-2">
                      <span className="font-bold text-slate-800">
                        Top {results.items.length} Chunks
                      </span>
                      <span>for &ldquo;{results.query}&rdquo;</span>
                      <span className="px-2 py-0.5 rounded-md bg-indigo-100 text-indigo-700 font-semibold uppercase text-[10px]">
                        {results.mode}
                      </span>
                    </div>
                    <div className="flex items-center space-x-1 text-slate-500">
                      <Clock className="w-3.5 h-3.5" />
                      <span>{results.duration_ms} ms</span>
                      <span>•</span>
                      <span>{results.total_results} total matches</span>
                    </div>
                  </div>

                  {results.items.length === 0 ? (
                    <div className="text-center py-12 text-slate-400 text-sm">
                      No matching chunks found for this query with mode "{results.mode}".
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {results.items.map((item, idx) => (
                        <ResultCard
                          key={item.chunk_id}
                          item={item}
                          rank={idx + 1}
                          query={query}
                          highlightFn={highlightTerms}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

interface ResultCardProps {
  item: SearchResultItem;
  rank: number;
  query: string;
  highlightFn: (text: string, q: string) => React.ReactNode;
}

const ResultCard: React.FC<ResultCardProps> = ({ item, rank, query, highlightFn }) => {
  const isTable = item.chunk_type === 'table';
  const fileUrl = `${getDocumentFileUrl(item.document_id)}#page=${item.page_start}`;

  return (
    <div className="p-4 rounded-xl bg-white border border-slate-200 hover:border-indigo-300 shadow-2xs transition-all text-left">
      {/* Top Header of Card */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex flex-wrap items-center gap-1.5 min-w-0">
          <span className="px-2 py-0.5 rounded-md font-bold text-xs bg-slate-900 text-white">
            #{rank}
          </span>

          {/* Fused Score / Main Score */}
          <span
            className="px-2 py-0.5 rounded-md font-mono font-semibold text-xs bg-indigo-100 text-indigo-800"
            title={`Overall retrieval score: ${item.score}`}
          >
            Score: {item.score.toFixed(4)}
          </span>

          {/* Breakdown Badges if available */}
          {item.vector_rank !== null && item.vector_rank !== undefined && (
            <span
              className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-200"
              title={`Vector Rank: #${item.vector_rank}, Cosine Similarity: ${item.vector_score?.toFixed(4)}`}
            >
              Vec: #{item.vector_rank} ({item.vector_score?.toFixed(3)})
            </span>
          )}

          {item.keyword_rank !== null && item.keyword_rank !== undefined && (
            <span
              className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200"
              title={`Keyword Rank: #${item.keyword_rank}, FTS Score: ${item.keyword_score?.toFixed(4)}`}
            >
              Key: #{item.keyword_rank} ({item.keyword_score?.toFixed(3)})
            </span>
          )}

          {isTable && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800 border border-amber-200 flex items-center space-x-1">
              <TableIcon className="w-2.5 h-2.5" />
              <span>Table</span>
            </span>
          )}
        </div>

        {/* Source link with page number */}
        <a
          href={fileUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center space-x-1 text-xs text-indigo-600 hover:text-indigo-800 font-semibold flex-shrink-0"
          title={`Open ${item.document_filename} at page ${item.page_start}`}
        >
          <span>
            {item.page_start === item.page_end ? `p. ${item.page_start}` : `p. ${item.page_start}–${item.page_end}`}
          </span>
          <ExternalLink className="w-3 h-3" />
        </a>
      </div>

      {/* Document & Heading Path Breadcrumb */}
      <div className="flex items-center space-x-1 text-[11px] text-slate-500 mb-2 truncate">
        <span className="font-semibold text-slate-700">{item.document_filename}</span>
        {item.heading_path && item.heading_path.length > 0 && (
          <>
            <ChevronRight className="w-3 h-3 text-slate-400 flex-shrink-0" />
            <span className="truncate text-indigo-700 font-medium">{item.heading_path.join(' › ')}</span>
          </>
        )}
      </div>

      {/* Text Snippet with Query Highlight */}
      <div className="text-xs text-slate-700 leading-relaxed bg-slate-50/70 p-3 rounded-lg border border-slate-100">
        {isTable ? (
          <div className="overflow-x-auto prose prose-xs max-w-none prose-table:border prose-th:p-1 prose-td:p-1">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.text}</ReactMarkdown>
          </div>
        ) : (
          <div className="line-clamp-4 whitespace-pre-wrap">
            {highlightFn(item.text, query)}
          </div>
        )}
      </div>
    </div>
  );
};
