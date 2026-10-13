import type { UploadedPaper } from './auth';
import type { Citation } from './chat';

export type SummaryStatus = 'pending' | 'generating' | 'ready' | 'failed';

export type OutlineSection = {
  heading: string;
  page_start: number;
  page_end: number;
};

export type SectionSummary = {
  heading: string;
  page_start: number;
  page_end: number;
  summary: string;
};

export type EquationExplanation = {
  page: number;
  raw_text: string;
  confidence: 'numbered' | 'heuristic';
  explanation: string;
  latex: string | null;
};

export type TranslationStatus = 'pending' | 'generating' | 'ready' | 'failed';

export type PaperSummaryResponse = {
  status: SummaryStatus;
  cached: boolean;
  generated_at: string | null;
  outline: OutlineSection[];
  section_summaries: SectionSummary[];
  overall_summary: string | null;
  equations: EquationExplanation[];
  methods: string[];
  error: string | null;
  language: string;
  translation_status: TranslationStatus | null;
};

export type FormatTemplateInfo = {
  id: string;
  name: string;
  description: string;
};

export type FormatReviewStatus = 'pending' | 'generating' | 'ready' | 'failed';

export type FormatChecklistItem = {
  id: string;
  name: string;
  required: boolean;
  present: boolean;
  heading: string | null;
  page_start: number | null;
  page_end: number | null;
};

export type FormatReviewFinding = {
  severity: 'missing' | 'issue' | 'suggestion';
  section: string;
  page: number | null;
  message: string;
  fix: string | null;
};

export type FormatReviewResponse = {
  status: FormatReviewStatus;
  cached: boolean;
  template_id: string;
  template_name: string;
  checklist: FormatChecklistItem[];
  findings: FormatReviewFinding[];
  generated_at: string | null;
  error: string | null;
  language: string;
  translation_status: TranslationStatus | null;
};

export type PaperSectionTranslationResponse = {
  status: TranslationStatus;
  cached: boolean;
  language: string;
  section_index: number;
  heading: string | null;
  translated_heading: string | null;
  translated_text: string | null;
  page_start: number | null;
  page_end: number | null;
  generated_at: string | null;
  error: string | null;
};

export type PaperCompareEntry = {
  paper: UploadedPaper;
  summary: string;
  cached: boolean;
  generated_at: string | null;
};

export type PaperCompareResponse = {
  papers: PaperCompareEntry[];
};

export type Difficulty = 'beginner' | 'intermediate' | 'expert';

export type ConceptExplanationResponse = {
  term: string;
  difficulty: Difficulty;
  explanation: string;
  citations: Citation[];
  language: string;
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
  lang: string | null = null,
): Promise<PaperSummaryResponse> {
  const query = new URLSearchParams({ ...(refresh ? { refresh: 'true' } : {}), ...(lang ? { lang } : {}) });
  const queryString = query.toString();
  return requestJson<PaperSummaryResponse>(`/papers/${paperId}/summary${queryString ? `?${queryString}` : ''}`, token);
}

export async function explainConceptApi(
  token: string,
  paperId: number | string,
  term: string,
  difficulty: Difficulty,
  lang: string | null = null,
): Promise<ConceptExplanationResponse> {
  return requestJson<ConceptExplanationResponse>(`/papers/${paperId}/explain`, token, {
    method: 'POST',
    body: JSON.stringify({ term, difficulty, ...(lang ? { lang } : {}) }),
  });
}

export async function listFormatTemplatesApi(token: string): Promise<FormatTemplateInfo[]> {
  return requestJson<FormatTemplateInfo[]>('/papers/format-templates', token);
}

export async function listLanguagesApi(token: string): Promise<Record<string, string>> {
  return requestJson<Record<string, string>>('/papers/languages', token);
}

export async function getFormatReviewApi(
  token: string,
  paperId: number | string,
  templateId: string,
  refresh = false,
  lang: string | null = null,
): Promise<FormatReviewResponse> {
  const query = new URLSearchParams({
    template: templateId,
    ...(refresh ? { refresh: 'true' } : {}),
    ...(lang ? { lang } : {}),
  });
  return requestJson<FormatReviewResponse>(`/papers/${paperId}/format-review?${query.toString()}`, token);
}

export async function runFormatReviewApi(
  token: string,
  paperId: number | string,
  templateId: string,
  lang: string | null = null,
): Promise<FormatReviewResponse> {
  const query = new URLSearchParams({ template: templateId, ...(lang ? { lang } : {}) });
  return requestJson<FormatReviewResponse>(`/papers/${paperId}/format-review?${query.toString()}`, token, {
    method: 'POST',
  });
}

export async function getSectionTranslationApi(
  token: string,
  paperId: number | string,
  sectionIndex: number,
  lang: string,
  refresh = false,
): Promise<PaperSectionTranslationResponse> {
  const query = new URLSearchParams({
    section_index: String(sectionIndex),
    lang,
    ...(refresh ? { refresh: 'true' } : {}),
  });
  return requestJson<PaperSectionTranslationResponse>(`/papers/${paperId}/translate-section?${query.toString()}`, token);
}

export async function runSectionTranslationApi(
  token: string,
  paperId: number | string,
  sectionIndex: number,
  lang: string,
): Promise<PaperSectionTranslationResponse> {
  const query = new URLSearchParams({ section_index: String(sectionIndex), lang });
  return requestJson<PaperSectionTranslationResponse>(`/papers/${paperId}/translate-section?${query.toString()}`, token, {
    method: 'POST',
  });
}

export async function comparePapersApi(token: string, paperIds: number[]): Promise<PaperCompareResponse> {
  const params = new URLSearchParams();
  paperIds.forEach((id) => params.append('paper_ids', String(id)));
  return requestJson<PaperCompareResponse>(`/papers/compare?${params.toString()}`, token);
}
