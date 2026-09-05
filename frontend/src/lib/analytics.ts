export type ActivityPoint = {
  date: string;
  questions_asked: number;
};

export type MostActivePaper = {
  paper_id: number;
  title: string;
  questions_asked: number;
};

export type MostCitedChunk = {
  paper_id: number;
  paper_title: string;
  page_start: number;
  page_end: number;
  times_cited: number;
};

export type AnalyticsSummaryResponse = {
  total_papers: number;
  total_questions_asked: number;
  most_active_paper: MostActivePaper | null;
  most_cited_chunks: MostCitedChunk[];
  activity_by_day: ActivityPoint[];
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

export async function getAnalyticsSummaryApi(token: string): Promise<AnalyticsSummaryResponse> {
  const response = await fetch(`${apiBaseUrl}/analytics/summary`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorBody?.detail ?? `Request failed with status ${response.status}`);
  }

  return response.json() as Promise<AnalyticsSummaryResponse>;
}
