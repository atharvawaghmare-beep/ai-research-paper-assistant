import type { Citation } from './chat';

export type PaperSummaryResponse = {
  summary: string;
  cached: boolean;
  generated_at: string | null;
};

export type Difficulty = 'beginner' | 'intermediate' | 'expert';

export type ConceptExplanationResponse = {
  term: string;
  difficulty: Difficulty;
  explanation: string;
  citations: Citation[];
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

export async function getPaperSummaryApi(
  token: string,
  paperId: number | string,
  refresh = false,
): Promise<PaperSummaryResponse> {
  const query = refresh ? '?refresh=true' : '';
  return requestJson<PaperSummaryResponse>(`/papers/${paperId}/summary${query}`, token);
}

export async function explainConceptApi(
  token: string,
  paperId: number | string,
  term: string,
  difficulty: Difficulty,
): Promise<ConceptExplanationResponse> {
  return requestJson<ConceptExplanationResponse>(`/papers/${paperId}/explain`, token, {
    method: 'POST',
    body: JSON.stringify({ term, difficulty }),
  });
}
