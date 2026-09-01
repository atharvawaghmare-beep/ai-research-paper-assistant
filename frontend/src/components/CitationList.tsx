import { useState } from 'react';
import type { Citation } from '../lib/chat';

function pageLabel(citation: { page_start: number; page_end: number }): string {
  return citation.page_start === citation.page_end
    ? `page ${citation.page_start}`
    : `pages ${citation.page_start}-${citation.page_end}`;
}

type CitationListProps = {
  citations: Citation[] | null | undefined;
  idPrefix: string;
};

export default function CitationList({ citations, idPrefix }: CitationListProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (!citations || citations.length === 0) {
    return null;
  }

  // When a session spans multiple papers (Phase 4), the same page number can
  // exist in more than one of them — show which paper each citation is from
  // so the label doesn't read as ambiguous.
  const isMultiPaper = new Set(citations.map((citation) => citation.paper_id)).size > 1;

  function toggle(key: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {citations.map((citation) => {
        const key = `${idPrefix}:${citation.marker}`;
        const isExpanded = expanded.has(key);
        // Spelled out rather than abbreviated ("S1 · pp. 1-2") so the label is
        // self-explanatory to someone who has never seen this UI before.
        const label = isMultiPaper
          ? `Source ${citation.marker} — ${citation.paper_title}, ${pageLabel(citation)}`
          : `Source ${citation.marker}, ${pageLabel(citation)}`;
        return (
          <div key={key} className="max-w-full">
            <button
              type="button"
              onClick={() => toggle(key)}
              className="inline-flex items-center gap-1 rounded-full border border-brand-100 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 transition hover:bg-brand-100"
            >
              {label}
              <span className="text-brand-400">{isExpanded ? '▲' : '▼'}</span>
            </button>
            {isExpanded && (
              <blockquote className="mt-1 max-w-sm rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
                “{citation.snippet.trim()}”
              </blockquote>
            )}
          </div>
        );
      })}
    </div>
  );
}
