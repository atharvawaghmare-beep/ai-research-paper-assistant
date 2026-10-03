import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  getRelatedPapersApi,
  importExternalPaperApi,
  type ExternalPaperResult,
  type RelatedPapersResponse,
} from '../lib/discover';

type RelatedPapersPanelProps = {
  paperId: string;
  isPaperReady: boolean;
};

type ImportState = 'idle' | 'importing' | 'imported' | 'error';

function resultKey(paper: ExternalPaperResult): string {
  return `${paper.source}:${paper.external_id}`;
}

function RelatedRow({
  paper,
  onImport,
  state,
  errorMessage,
}: {
  paper: ExternalPaperResult;
  onImport: () => void;
  state: ImportState;
  errorMessage?: string;
}) {
  const similarity = paper.recommendation_score ?? 0;
  return (
    <div className="flex items-start justify-between gap-3 border-b border-slate-100 py-3 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className="rounded-full border border-brand-200 bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700"
            title="Cosine similarity between this paper's abstract and the candidate's title + abstract"
          >
            {Math.round(similarity * 100)}% similar
          </span>
          {paper.year && <span className="text-[11px] text-slate-400">{paper.year}</span>}
          {paper.matched_categories.map((category) => (
            <span
              key={category}
              className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-500"
            >
              {category}
            </span>
          ))}
        </div>
        <p className="mt-0.5 text-sm font-medium text-slate-800">
          {paper.external_url ? (
            <a href={paper.external_url} target="_blank" rel="noreferrer" className="hover:underline">
              {paper.title}
            </a>
          ) : (
            paper.title
          )}
        </p>
        {paper.authors.length > 0 && <p className="truncate text-xs text-slate-500">{paper.authors.join(', ')}</p>}
        {paper.abstract && <p className="mt-1 line-clamp-2 text-xs text-slate-500">{paper.abstract}</p>}
        {errorMessage && <p className="mt-1 text-xs text-rose-600">{errorMessage}</p>}
      </div>

      {state === 'imported' ? (
        <span className="shrink-0 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
          Added
        </span>
      ) : (
        <button
          type="button"
          onClick={onImport}
          disabled={!paper.importable || state === 'importing'}
          title={paper.importable ? undefined : 'No open-access PDF is available for this paper'}
          className="shrink-0 rounded-full bg-brand-600 px-3 py-1 text-xs font-medium text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {state === 'importing' ? 'Adding...' : 'Import'}
        </button>
      )}
    </div>
  );
}

export default function RelatedPapersPanel({ paperId, isPaperReady }: RelatedPapersPanelProps) {
  const { token } = useAuth();
  const [data, setData] = useState<RelatedPapersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [importStates, setImportStates] = useState<Record<string, ImportState>>({});
  const [importErrors, setImportErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!token || !isPaperReady) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    getRelatedPapersApi(token, paperId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load related papers');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, paperId, isPaperReady]);

  async function handleImport(paper: ExternalPaperResult) {
    if (!token) return;
    const key = resultKey(paper);
    setImportStates((current) => ({ ...current, [key]: 'importing' }));
    setImportErrors((current) => ({ ...current, [key]: '' }));
    try {
      await importExternalPaperApi(token, paper);
      setImportStates((current) => ({ ...current, [key]: 'imported' }));
    } catch (err) {
      setImportStates((current) => ({ ...current, [key]: 'error' }));
      setImportErrors((current) => ({ ...current, [key]: err instanceof Error ? err.message : 'Import failed' }));
    }
  }

  if (!isPaperReady) {
    return (
      <div className="grid h-full place-items-center px-5 text-center text-sm text-slate-500">
        Related papers will be available once this paper finishes processing.
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto px-5 py-6">
      {loading ? (
        <div className="grid place-items-center py-10 text-sm text-slate-500">
          Reading the paper and searching arXiv for related work...
        </div>
      ) : error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
      ) : (
        <div className="space-y-6">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">How these were found</h3>
            <p className="mt-1 text-xs text-slate-500">
              The local AI model read this paper and extracted its key topics
              {data?.query.abstract_source === 'opening_text' ? ' (no abstract was found, so its opening text was used)' : ''}.
              arXiv was searched for those phrases, and results are ranked by how semantically close each abstract is to
              this paper. Papers already in your library are hidden.
            </p>
            {data && data.query.key_phrases.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {data.query.key_phrases.map((phrase) => (
                  <span
                    key={phrase}
                    className="rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-xs text-slate-700"
                  >
                    {phrase}
                  </span>
                ))}
                {data.query.categories.map((category) => (
                  <span
                    key={category}
                    className="rounded-full border border-brand-200 bg-brand-50 px-2.5 py-0.5 text-xs font-medium text-brand-700"
                  >
                    {category}
                  </span>
                ))}
              </div>
            )}
          </div>

          {data && data.warnings.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {data.warnings.join(' ')}
            </div>
          )}

          {data && data.results.length === 0 ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
              {data.message ?? 'No related papers found.'}
            </div>
          ) : (
            <div>
              <h3 className="text-sm font-semibold text-slate-900">Related papers on arXiv</h3>
              <div className="mt-1">
                {data?.results.map((paper) => {
                  const key = resultKey(paper);
                  return (
                    <RelatedRow
                      key={key}
                      paper={paper}
                      onImport={() => void handleImport(paper)}
                      state={importStates[key] ?? 'idle'}
                      errorMessage={importErrors[key]}
                    />
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
