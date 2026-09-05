import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  getPaperCitationsApi,
  importExternalPaperApi,
  type ExternalPaperResult,
  type PaperCitationsResponse,
} from '../lib/discover';

type CitationsPanelProps = {
  paperId: string;
  isPaperReady: boolean;
};

type ImportState = 'idle' | 'importing' | 'imported' | 'error';

const SOURCE_LABELS: Record<ExternalPaperResult['source'], string> = {
  arxiv: 'arXiv',
  semantic_scholar: 'Semantic Scholar',
};

function resultKey(paper: ExternalPaperResult): string {
  return `${paper.source}:${paper.external_id}`;
}

// A small radial node-link diagram: the paper itself at the center, its
// references fanned out above, papers that cite it fanned out below. It's a
// preview (capped to a handful of nodes per side for legibility), not an
// exhaustive graph — the full lists below carry the rest.
function CitationGraph({
  references,
  citingPapers,
}: {
  references: ExternalPaperResult[];
  citingPapers: ExternalPaperResult[];
}) {
  const width = 420;
  const height = 260;
  const cx = width / 2;
  const cy = height / 2;
  const radius = 95;
  const maxPerSide = 5;

  function arcPositions(count: number, direction: 1 | -1) {
    if (count === 0) return [];
    const spreadDeg = count === 1 ? 0 : 60;
    return Array.from({ length: count }, (_, index) => {
      const t = count === 1 ? 0 : -spreadDeg + (2 * spreadDeg * index) / (count - 1);
      const radians = (t * Math.PI) / 180;
      return {
        x: cx + radius * Math.sin(radians),
        y: cy + direction * radius * Math.cos(radians),
      };
    });
  }

  const refNodes = references.slice(0, maxPerSide);
  const citingNodes = citingPapers.slice(0, maxPerSide);
  const refPositions = arcPositions(refNodes.length, -1);
  const citingPositions = arcPositions(citingNodes.length, 1);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="mx-auto block w-full max-w-md" role="img" aria-label="Citation graph">
      {refNodes.map((paper, index) => (
        <line
          key={`ref-line-${resultKey(paper)}`}
          x1={cx}
          y1={cy}
          x2={refPositions[index].x}
          y2={refPositions[index].y}
          stroke="#c7d2fe"
          strokeWidth={1.5}
        />
      ))}
      {citingNodes.map((paper, index) => (
        <line
          key={`cite-line-${resultKey(paper)}`}
          x1={cx}
          y1={cy}
          x2={citingPositions[index].x}
          y2={citingPositions[index].y}
          stroke="#fde68a"
          strokeWidth={1.5}
        />
      ))}

      <circle cx={cx} cy={cy} r={22} fill="#0f172a" />
      <text x={cx} y={cy + 4} textAnchor="middle" fontSize={9} fill="white" fontWeight={600}>
        This paper
      </text>

      {refNodes.map((paper, index) => (
        <g key={`ref-node-${resultKey(paper)}`}>
          <title>{paper.title}</title>
          <circle cx={refPositions[index].x} cy={refPositions[index].y} r={14} fill="#6366f1" />
          <text x={refPositions[index].x} y={refPositions[index].y + 4} textAnchor="middle" fontSize={9} fill="white" fontWeight={600}>
            R{index + 1}
          </text>
        </g>
      ))}

      {citingNodes.map((paper, index) => (
        <g key={`cite-node-${resultKey(paper)}`}>
          <title>{paper.title}</title>
          <circle cx={citingPositions[index].x} cy={citingPositions[index].y} r={14} fill="#d97706" />
          <text x={citingPositions[index].x} y={citingPositions[index].y + 4} textAnchor="middle" fontSize={9} fill="white" fontWeight={600}>
            C{index + 1}
          </text>
        </g>
      ))}

      <g transform={`translate(12, ${height - 24})`}>
        <circle cx={0} cy={0} r={5} fill="#6366f1" />
        <text x={10} y={4} fontSize={10} fill="#475569">References (R)</text>
        <circle cx={130} cy={0} r={5} fill="#d97706" />
        <text x={140} y={4} fontSize={10} fill="#475569">Cited by (C)</text>
      </g>
    </svg>
  );
}

function PaperRow({
  paper,
  badge,
  onImport,
  state,
  errorMessage,
}: {
  paper: ExternalPaperResult;
  badge: string;
  onImport: () => void;
  state: ImportState;
  errorMessage?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-slate-100 py-3 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold text-slate-500">
            {badge}
          </span>
          <span className="text-[11px] text-slate-400">{SOURCE_LABELS[paper.source]}</span>
          {paper.year && <span className="text-[11px] text-slate-400">{paper.year}</span>}
          {typeof paper.citation_count === 'number' && (
            <span className="text-[11px] text-slate-400">{paper.citation_count} citations</span>
          )}
        </div>
        <p className="mt-0.5 truncate text-sm font-medium text-slate-800">{paper.title}</p>
        {paper.authors.length > 0 && <p className="truncate text-xs text-slate-500">{paper.authors.join(', ')}</p>}
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

export default function CitationsPanel({ paperId, isPaperReady }: CitationsPanelProps) {
  const { token } = useAuth();
  const [data, setData] = useState<PaperCitationsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [importStates, setImportStates] = useState<Record<string, ImportState>>({});
  const [importErrors, setImportErrors] = useState<Record<string, string>>({});

  async function load(refresh = false) {
    if (!token || !isPaperReady) return;
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError('');

    try {
      const result = await getPaperCitationsApi(token, paperId, refresh);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load citation data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      setImportErrors((current) => ({
        ...current,
        [key]: err instanceof Error ? err.message : 'Import failed',
      }));
    }
  }

  if (!isPaperReady) {
    return (
      <div className="grid h-full place-items-center px-5 text-center text-sm text-slate-500">
        Citation data will be available once this paper finishes processing.
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto px-5 py-6">
      {loading ? (
        <div className="grid place-items-center py-10 text-sm text-slate-500">Loading citation data...</div>
      ) : error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
      ) : !data?.available ? (
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
          {data?.message ?? 'No citation data available for this paper.'}
        </div>
      ) : (
        <div className="space-y-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-4 text-sm text-slate-600">
              <span>
                <strong className="text-slate-900">{data.citation_count ?? 0}</strong> citations
              </span>
              <span>
                <strong className="text-slate-900">{data.reference_count ?? 0}</strong> references
              </span>
            </div>
            <button
              type="button"
              onClick={() => void load(true)}
              disabled={refreshing}
              className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {refreshing ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>

          {(data.references.length > 0 || data.citing_papers.length > 0) && (
            <CitationGraph references={data.references} citingPapers={data.citing_papers} />
          )}

          {data.related_papers.length > 0 && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">Related papers</h3>
              <div className="rounded-xl border border-slate-200 bg-white px-4">
                {data.related_papers.map((paper, index) => {
                  const key = resultKey(paper);
                  return (
                    <PaperRow
                      key={key}
                      paper={paper}
                      badge={`#${index + 1}`}
                      onImport={() => void handleImport(paper)}
                      state={importStates[key] ?? 'idle'}
                      errorMessage={importErrors[key]}
                    />
                  );
                })}
              </div>
            </section>
          )}

          {data.references.length > 0 && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">References ({data.references.length})</h3>
              <div className="rounded-xl border border-slate-200 bg-white px-4">
                {data.references.map((paper, index) => {
                  const key = resultKey(paper);
                  return (
                    <PaperRow
                      key={key}
                      paper={paper}
                      badge={`R${index + 1}`}
                      onImport={() => void handleImport(paper)}
                      state={importStates[key] ?? 'idle'}
                      errorMessage={importErrors[key]}
                    />
                  );
                })}
              </div>
            </section>
          )}

          {data.citing_papers.length > 0 && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">Cited by ({data.citing_papers.length})</h3>
              <div className="rounded-xl border border-slate-200 bg-white px-4">
                {data.citing_papers.map((paper, index) => {
                  const key = resultKey(paper);
                  return (
                    <PaperRow
                      key={key}
                      paper={paper}
                      badge={`C${index + 1}`}
                      onImport={() => void handleImport(paper)}
                      state={importStates[key] ?? 'idle'}
                      errorMessage={importErrors[key]}
                    />
                  );
                })}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
