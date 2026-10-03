import type { UploadedPaper } from './auth';

export type Citation = {
  marker: number;
  chunk_id: number;
  paper_id: number;
  paper_title: string;
  page_start: number;
  page_end: number;
  snippet: string;
};

export type ChatMessage = {
  id: number;
  session_id: number;
  message_index: number;
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[] | null;
  created_at: string;
};

export type ChatSession = {
  id: number;
  user_id: number;
  paper_id: number | null;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
  papers: UploadedPaper[];
};

export type ChatSessionWithMessages = ChatSession & {
  messages: ChatMessage[];
};

export type ChatTurnResponse = {
  session_id: number;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
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

export async function listChatSessionsApi(token: string, paperId: number | string): Promise<ChatSession[]> {
  return requestJson<ChatSession[]>(`/papers/${paperId}/chat`, token);
}

export async function getChatSessionApi(
  token: string,
  paperId: number | string,
  sessionId: number,
): Promise<ChatSessionWithMessages> {
  return requestJson<ChatSessionWithMessages>(`/papers/${paperId}/chat/${sessionId}`, token);
}

export async function sendChatMessageApi(
  token: string,
  paperId: number | string,
  message: string,
  sessionId: number | null,
  additionalPaperIds: number[] = [],
): Promise<ChatTurnResponse> {
  return requestJson<ChatTurnResponse>(`/papers/${paperId}/chat`, token, {
    method: 'POST',
    body: JSON.stringify({ message, session_id: sessionId, additional_paper_ids: additionalPaperIds }),
  });
}
