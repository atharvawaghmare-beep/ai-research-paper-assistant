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
  categories: string[];
  recommendation_score: number | null;
  matched_categories: string[];
};

export type PaperSearchResponse = {
  query: string;
  results: ExternalPaperResult[];
  warnings: string[];
};

export type PaperRecommendationResponse = {
  recommendations: ExternalPaperResult[];
  interest_profile: Record<string, number>;
  warnings: string[];
  message: string | null;
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

export type DiscoverSort = 'relevance' | 'recent';

export async function searchExternalPapersApi(
  token: string,
  options: { query?: string; categories?: string[]; sort?: DiscoverSort; limit?: number },
): Promise<PaperSearchResponse> {
  const params = new URLSearchParams();
  if (options.query) params.set('q', options.query);
  if (options.sort) params.set('sort', options.sort);
  params.set('limit', String(options.limit ?? 10));
  (options.categories ?? []).forEach((category) => params.append('category', category));

  return requestJson<PaperSearchResponse>(`/papers/search?${params.toString()}`, token);
}

export async function getDiscoverCategoriesApi(token: string): Promise<Record<string, string>> {
  return requestJson<Record<string, string>>('/papers/categories', token);
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
      categories: paper.categories,
    }),
  });
}

export async function getPaperRecommendationsApi(token: string, limit = 10): Promise<PaperRecommendationResponse> {
  return requestJson<PaperRecommendationResponse>(`/papers/recommendations?limit=${limit}`, token);
}

export async function getPaperCitationsApi(
  token: string,
  paperId: number | string,
  refresh = false,
): Promise<PaperCitationsResponse> {
  const query = refresh ? '?refresh=true' : '';
  return requestJson<PaperCitationsResponse>(`/papers/${paperId}/citations${query}`, token);
}
