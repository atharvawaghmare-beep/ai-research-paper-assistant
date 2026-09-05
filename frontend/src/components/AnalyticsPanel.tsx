import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { getAnalyticsSummaryApi, type ActivityPoint, type AnalyticsSummaryResponse } from '../lib/analytics';

const CHART_WIDTH = 640;
const CHART_HEIGHT = 200;
const PADDING_LEFT = 28;
const PADDING_RIGHT = 8;
const PADDING_TOP = 16;
const PADDING_BOTTOM = 22;
const MAX_BAR_WIDTH = 24;
const BAR_GAP = 3;
const BAR_COLOR = '#6366f1'; // brand-500 — the same hue already used for interactive accents elsewhere
const BAR_COLOR_HOVER = '#4f46e5'; // brand-600

function formatDayLabel(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

// A single-series bar chart needs no legend box (the title already names the one
// series) — just clean gridlines, a hover/focus tooltip carrying the same value a
// direct label would, and thin bars that never fill their slot.
function ActivityChart({ points }: { points: ActivityPoint[] }) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const chartWidth = CHART_WIDTH - PADDING_LEFT - PADDING_RIGHT;
  const chartHeight = CHART_HEIGHT - PADDING_TOP - PADDING_BOTTOM;
  const maxValue = Math.max(...points.map((point) => point.questions_asked), 0);
  const niceMax = maxValue <= 4 ? Math.max(1, maxValue) : Math.ceil(maxValue / 5) * 5;

  const barWidth = Math.min(MAX_BAR_WIDTH, chartWidth / points.length - BAR_GAP);
  const totalWidth = points.length * (barWidth + BAR_GAP) - BAR_GAP;
  const startX = PADDING_LEFT + Math.max(0, (chartWidth - totalWidth) / 2);

  function yFor(value: number): number {
    return PADDING_TOP + chartHeight - (value / niceMax) * chartHeight;
  }

  function roundedTopBarPath(x: number, top: number, bottom: number, width: number): string {
    const radius = Math.min(4, width / 2, Math.max(0, bottom - top));
    if (bottom - top <= 0.5) {
      return `M${x},${bottom} L${x + width},${bottom}`;
    }
    return [
      `M${x},${bottom}`,
      `L${x},${top + radius}`,
      `Q${x},${top} ${x + radius},${top}`,
      `L${x + width - radius},${top}`,
      `Q${x + width},${top} ${x + width},${top + radius}`,
      `L${x + width},${bottom}`,
      'Z',
    ].join(' ');
  }

  const gridValues = niceMax <= 1 ? [0, niceMax] : [0, niceMax / 2, niceMax];
  const baseline = yFor(0);
  const hovered = hoveredIndex !== null ? points[hoveredIndex] : null;

  return (
    <svg
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      className="w-full"
      role="img"
      aria-label={`Questions asked per day, last ${points.length} days`}
    >
      {gridValues.map((value) => {
        const y = yFor(value);
        return (
          <g key={value}>
            <line x1={PADDING_LEFT} y1={y} x2={CHART_WIDTH - PADDING_RIGHT} y2={y} stroke="#e2e8f0" strokeWidth={1} />
            <text x={PADDING_LEFT - 6} y={y + 3} textAnchor="end" fontSize={9} fill="#94a3b8">
              {value}
            </text>
          </g>
        );
      })}

      {points.map((point, index) => {
        const x = startX + index * (barWidth + BAR_GAP);
        const top = yFor(point.questions_asked);
        const isHovered = hoveredIndex === index;
        const showLabel = points.length <= 10 || index % 2 === 0;

        return (
          <g
            key={point.date}
            tabIndex={0}
            role="img"
            aria-label={`${formatDayLabel(point.date)}: ${point.questions_asked} question${point.questions_asked === 1 ? '' : 's'}`}
            onMouseEnter={() => setHoveredIndex(index)}
            onMouseLeave={() => setHoveredIndex((current) => (current === index ? null : current))}
            onFocus={() => setHoveredIndex(index)}
            onBlur={() => setHoveredIndex((current) => (current === index ? null : current))}
            style={{ cursor: 'pointer', outline: 'none' }}
          >
            {/* Wider transparent hit area than the visible bar — easier to hover/focus precisely. */}
            <rect x={x - BAR_GAP} y={PADDING_TOP} width={barWidth + BAR_GAP * 2} height={chartHeight} fill="transparent" />
            <path d={roundedTopBarPath(x, top, baseline, barWidth)} fill={isHovered ? BAR_COLOR_HOVER : BAR_COLOR} />
            {showLabel && (
              <text x={x + barWidth / 2} y={CHART_HEIGHT - 6} textAnchor="middle" fontSize={8} fill="#94a3b8">
                {formatDayLabel(point.date)}
              </text>
            )}
          </g>
        );
      })}

      {hovered &&
        hoveredIndex !== null &&
        (() => {
          const x = startX + hoveredIndex * (barWidth + BAR_GAP) + barWidth / 2;
          const top = yFor(hovered.questions_asked);
          const label = `${formatDayLabel(hovered.date)}: ${hovered.questions_asked}`;
          const tooltipWidth = Math.max(56, label.length * 5.4 + 12);
          const tooltipX = Math.min(Math.max(x - tooltipWidth / 2, PADDING_LEFT), CHART_WIDTH - PADDING_RIGHT - tooltipWidth);
          const tooltipY = Math.max(0, top - 24);
          return (
            <g>
              <rect x={tooltipX} y={tooltipY} width={tooltipWidth} height={18} rx={4} fill="#0f172a" />
              <text x={tooltipX + tooltipWidth / 2} y={tooltipY + 13} textAnchor="middle" fontSize={9} fill="white">
                {label}
              </text>
            </g>
          );
        })()}
    </svg>
  );
}

export default function AnalyticsPanel() {
  const { token } = useAuth();
  const [data, setData] = useState<AnalyticsSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    getAnalyticsSummaryApi(token)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Unable to load analytics');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  if (loading) {
    return <p className="text-sm text-slate-500">Loading activity...</p>;
  }

  if (error) {
    return <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">{error}</div>;
  }

  if (!data) return null;

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold text-slate-900">Activity</h2>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
          <p className="text-xs font-medium text-slate-500">Total papers</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900">{data.total_papers}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
          <p className="text-xs font-medium text-slate-500">Questions asked</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900">{data.total_questions_asked}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
          <p className="text-xs font-medium text-slate-500">Most active paper</p>
          {data.most_active_paper ? (
            <>
              <p className="mt-1 truncate text-sm font-semibold text-slate-900">{data.most_active_paper.title}</p>
              <p className="text-xs text-slate-500">{data.most_active_paper.questions_asked} questions</p>
            </>
          ) : (
            <p className="mt-1 text-sm text-slate-400">No chat activity yet</p>
          )}
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
        <p className="mb-2 text-sm font-medium text-slate-800">Questions asked, last {data.activity_by_day.length} days</p>
        {data.total_questions_asked === 0 ? (
          <p className="py-8 text-center text-sm text-slate-400">Ask a paper something to see activity here.</p>
        ) : (
          <ActivityChart points={data.activity_by_day} />
        )}
      </div>

      {data.most_cited_chunks.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
          <p className="mb-3 text-sm font-medium text-slate-800">Most-cited pages</p>
          <div className="divide-y divide-slate-100">
            {data.most_cited_chunks.map((chunk) => (
              <div key={`${chunk.paper_id}-${chunk.page_start}-${chunk.page_end}`} className="flex items-center justify-between gap-3 py-2 text-sm">
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-800">{chunk.paper_title}</p>
                  <p className="text-xs text-slate-500">
                    {chunk.page_start === chunk.page_end ? `page ${chunk.page_start}` : `pages ${chunk.page_start}-${chunk.page_end}`}
                  </p>
                </div>
                <span className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600">
                  cited {chunk.times_cited}×
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
