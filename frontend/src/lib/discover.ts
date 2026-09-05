import type { UploadedPaper } from './auth';

export type ExternalPaperSource = 'arxiv' | 'semantic_scholar';

export type ExternalPaperResult = {
  source: ExternalPaperSource;
  external_id: string;
  title: string;
  authors: string[];
  abstract: string | null;
  year: number | null;
  pdf_url: string | null;
  external_url: string | null;
  importable: boolean;
  citation_count: number | null;
};

export type PaperSearchResponse = {
  query: string;
  results: ExternalPaperResult[];
  warnings: string[];
};

export type PaperCitationsResponse = {
  paper_id: number;
  available: boolean;
  citation_count: number | null;
  reference_count: number | null;
  references: ExternalPaperResult[];
  citing_papers: ExternalPaperResult[];
  related_papers: ExternalPaperResult[];
  fetched_at: string | null;
  message: string | null;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

async function requestJson<T>(path: string, token: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(options?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorBody?.detail ?? `Request failed with status ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function searchExternalPapersApi(token: string, query: string, limit = 10): Promise<PaperSearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return requestJson<PaperSearchResponse>(`/papers/search?${params.toString()}`, token);
}

export async function importExternalPaperApi(token: string, paper: ExternalPaperResult): Promise<UploadedPaper> {
  return requestJson<UploadedPaper>('/papers/import', token, {
    method: 'POST',
    body: JSON.stringify({
      source: paper.source,
      external_id: paper.external_id,
      pdf_url: paper.pdf_url,
      title: paper.title,
      external_url: paper.external_url,
    }),
  });
}

export async function getPaperCitationsApi(
  token: string,
  paperId: number | string,
  refresh = false,
): Promise<PaperCitationsResponse> {
  const query = refresh ? '?refresh=true' : '';
  return requestJson<PaperCitationsResponse>(`/papers/${paperId}/citations${query}`, token);
}
