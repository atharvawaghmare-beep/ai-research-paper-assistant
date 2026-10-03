import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
  getPaperRecommendationsApi,
  importExternalPaperApi,
  type ExternalPaperResult,
  type PaperRecommendationResponse,
} from '../lib/discover';

type ImportState = 'idle' | 'importing' | 'imported' | 'error';

function resultKey(paper: ExternalPaperResult): string {
  return `${paper.source}:${paper.external_id}`;
}

function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength).trimEnd()}...`;
}

function scoreLabel(score: number | null): string {
  return score === null ? '' : `${Math.round(score * 100)}% match`;
}

export default function RecommendationsPanel() {
  const { token } = useAuth();
  const [data, setData] = useState<PaperRecommendationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [importStates, setImportStates] = useState<Record<string, ImportState>>({});
  const [importErrors, setImportErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    setError('');
    getPaperRecommendationsApi(token)
      .then(setData)
      .catch((requestError) => setError(requestError instanceof Error ? requestError.message : 'Unable to load recommendations'))
      .finally(() => setLoading(false));
  }, [token]);

  async function handleImport(paper: ExternalPaperResult) {
    if (!token) return;
    const key = resultKey(paper);
    setImportStates((current) => ({ ...current, [key]: 'importing' }));
    setImportErrors((current) => ({ ...current, [key]: '' }));

    try {
      await importExternalPaperApi(token, paper);
      setImportStates((current) => ({ ...current, [key]: 'imported' }));
    } catch (requestError) {
      setImportStates((current) => ({ ...current, [key]: 'error' }));
      setImportErrors((current) => ({
        ...current,
        [key]: requestError instanceof Error ? requestError.message : 'Import failed',
      }));
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Recommended for you</h2>
          <p className="text-sm text-slate-500">Recent arXiv papers matched to the topics of papers you've imported, uploaded and viewed — from their categories, or from their content when the AI model has read them.</p>
        </div>
        <Link to="/discover" className="text-sm font-medium text-brand-600 hover:text-brand-700">
          Browse all papers
        </Link>
      </div>

      {loading && <p className="text-sm text-slate-500">Finding papers for you...</p>}
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">{error}</div>}

      {!loading && !error && data?.interest_profile && Object.keys(data.interest_profile).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(data.interest_profile).slice(0, 3).map(([category, weight]) => (
            <span key={category} className="rounded-full border border-brand-100 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700">
              {category} · {Math.round(weight * 100)}%
            </span>
          ))}
        </div>
      )}

      {!loading && !error && data?.warnings.map((warning) => (
        <p key={warning} className="text-sm text-amber-700">{warning}</p>
      ))}

      {!loading && !error && data?.message && (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-5 py-6 text-sm text-slate-600">
          {data.message}
        </div>
      )}

      {!loading && !error && data && !data.message && data.recommendations.length === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-5 py-6 text-sm text-slate-600">
          No new matches are available right now. Check back after new papers are submitted.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {data?.recommendations.map((paper) => {
          const key = resultKey(paper);
          const state = importStates[key] ?? 'idle';
          return (
            <article key={key} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-xs font-medium text-slate-600">arXiv</span>
                    {paper.year && <span className="text-xs text-slate-400">{paper.year}</span>}
                    {paper.recommendation_score !== null && (
                      <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">
                        {scoreLabel(paper.recommendation_score)}
                      </span>
                    )}
                  </div>
                  <h3 className="mt-2 text-base font-semibold text-slate-900">{paper.title}</h3>
                  {paper.authors.length > 0 && <p className="mt-1 text-sm text-slate-500">{paper.authors.join(', ')}</p>}
                </div>
                {state === 'imported' ? (
                  <span className="shrink-0 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">Added</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => void handleImport(paper)}
                    disabled={!paper.importable || state === 'importing'}
                    className="shrink-0 rounded-full bg-brand-600 px-3.5 py-1.5 text-xs font-medium text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {state === 'importing' ? 'Adding...' : 'Add'}
                  </button>
                )}
              </div>
              {paper.matched_categories.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {paper.matched_categories.map((category) => (
                    <span key={category} className="rounded-full border border-brand-100 bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700">{category}</span>
                  ))}
                </div>
              )}
              {paper.abstract && <p className="mt-3 text-sm text-slate-600">{truncate(paper.abstract, 220)}</p>}
              {state === 'error' && importErrors[key] && <p className="mt-3 text-sm text-rose-600">{importErrors[key]}</p>}
            </article>
          );
        })}
      </div>
    </section>
  );
}
