import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
  importExternalPaperApi,
  searchExternalPapersApi,
  type ExternalPaperResult,
} from '../lib/discover';

type ImportState = 'idle' | 'importing' | 'imported' | 'error';

const SOURCE_LABELS: Record<ExternalPaperResult['source'], string> = {
  arxiv: 'arXiv',
  semantic_scholar: 'Semantic Scholar',
};

function resultKey(paper: ExternalPaperResult): string {
  return `${paper.source}:${paper.external_id}`;
}

function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength).trimEnd()}...`;
}

export default function DiscoverPage() {
  const { token } = useAuth();
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [results, setResults] = useState<ExternalPaperResult[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [importStates, setImportStates] = useState<Record<string, ImportState>>({});
  const [importErrors, setImportErrors] = useState<Record<string, string>>({});

  async function handleSearch(event: React.FormEvent) {
    event.preventDefault();
    if (!token) return;

    const trimmed = query.trim();
    if (!trimmed) {
      setSearchError('Enter a title or keyword to search.');
      return;
    }

    setIsSearching(true);
    setSearchError('');
    setWarnings([]);

    try {
      const response = await searchExternalPapersApi(token, trimmed);
      setResults(response.results);
      setWarnings(response.warnings);
      setHasSearched(true);
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : 'Search failed');
      setResults([]);
    } finally {
      setIsSearching(false);
    }
  }

  async function handleImport(paper: ExternalPaperResult) {
    if (!token) return;
    const key = resultKey(paper);

    setImportStates((current) => ({ ...current, [key]: 'importing' }));
    setImportErrors((current) => ({ ...current, [key]: '' }));

    try {
      await importExternalPaperApi(token, paper);
      setImportStates((current) => ({ ...current, [key]: 'imported' }));
    } catch (error) {
      setImportStates((current) => ({ ...current, [key]: 'error' }));
      setImportErrors((current) => ({
        ...current,
        [key]: error instanceof Error ? error.message : 'Import failed',
      }));
    }
  }

  return (
    <section className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-slate-900">Discover papers</h1>
      </header>

      <form onSubmit={(event) => void handleSearch(event)} className="flex flex-col gap-3 sm:flex-row">
        <input
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="e.g. retrieval augmented generation"
          className="flex-1 rounded-xl border border-slate-300 px-4 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100"
        />
        <button
          type="submit"
          disabled={isSearching}
          className="rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSearching ? 'Searching...' : 'Search'}
        </button>
      </form>

      {searchError && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">{searchError}</div>
      )}

      {warnings.length > 0 && (
        <div className="space-y-1 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
          {warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      )}

      <div className="space-y-4">
        {hasSearched && !isSearching && results.length === 0 && !searchError && (
          <p className="text-sm text-slate-500">No results found for that search.</p>
        )}

        {results.map((paper) => {
          const key = resultKey(paper);
          const state = importStates[key] ?? 'idle';

          return (
            <article key={key} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-xs font-medium text-slate-600">
                      {SOURCE_LABELS[paper.source]}
                    </span>
                    {paper.year && <span className="text-xs text-slate-400">{paper.year}</span>}
                  </div>
                  <h3 className="mt-1.5 text-base font-semibold text-slate-900">{paper.title}</h3>
                  {paper.authors.length > 0 && (
                    <p className="mt-0.5 text-sm text-slate-500">{paper.authors.join(', ')}</p>
                  )}
                  {paper.abstract && (
                    <p className="mt-2 text-sm text-slate-600">{truncate(paper.abstract, 320)}</p>
                  )}
                  {paper.external_url && (
                    <a
                      href={paper.external_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-block text-xs font-medium text-brand-600 hover:text-brand-700"
                    >
                      View source page ↗
                    </a>
                  )}
                </div>

                <div className="flex shrink-0 flex-col items-end gap-2">
                  {state === 'imported' ? (
                    <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3.5 py-1.5 text-sm font-medium text-emerald-700">
                      Added to library
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void handleImport(paper)}
                      disabled={!paper.importable || state === 'importing'}
                      title={paper.importable ? undefined : 'No open-access PDF is available for this result'}
                      className="rounded-full bg-brand-600 px-3.5 py-1.5 text-sm font-medium text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {state === 'importing' ? 'Adding...' : 'Add to my library'}
                    </button>
                  )}
                  {!paper.importable && state !== 'imported' && (
                    <span className="text-xs text-slate-400">No PDF available</span>
                  )}
                </div>
              </div>

              {state === 'error' && importErrors[key] && (
                <p className="mt-3 text-sm text-rose-600">{importErrors[key]}</p>
              )}
            </article>
          );
        })}
      </div>

      {results.some((paper) => (importStates[resultKey(paper)] ?? 'idle') === 'imported') && (
        <p className="text-sm text-slate-500">
          Imported papers appear on your <Link to="/dashboard" className="font-medium text-brand-600 hover:text-brand-700">dashboard</Link> and process the same way as an upload.
        </p>
      )}
    </section>
  );
}
