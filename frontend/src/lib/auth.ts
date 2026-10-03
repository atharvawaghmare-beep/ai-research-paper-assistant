export type AuthUser = {
  id: number;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string;
};

export type AuthPayload = {
  token: {
    access_token: string;
    token_type: 'bearer';
  };
  user: AuthUser;
};

export type UploadedPaper = {
  id: number;
  user_id: number;
  title: string;
  original_filename: string;
  storage_path: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  checksum_sha256: string | null;
  processing_status: string;
  page_count: number | null;
  paper_metadata: Record<string, unknown> | null;
  uploaded_at: string;
  processed_at: string | null;
  summary_generated_at: string | null;
  last_viewed_at: string | null;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {}),
    },
    ...options,
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorBody?.detail ?? `Request failed with status ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function getStoredToken(): string | null {
  return localStorage.getItem('access_token');
}

export function storeToken(token: string | null): void {
  if (token === null) {
    localStorage.removeItem('access_token');
    return;
  }

  localStorage.setItem('access_token', token);
}

export async function signupApi(payload: { email: string; password: string; full_name?: string | null }): Promise<AuthPayload> {
  return requestJson<AuthPayload>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function loginApi(payload: { email: string; password: string }): Promise<AuthPayload> {
  return requestJson<AuthPayload>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function currentUserApi(token: string): Promise<AuthUser> {
  const response = await fetch(`${apiBaseUrl}/auth/me`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorBody?.detail ?? `Request failed with status ${response.status}`);
  }

  return response.json() as Promise<AuthUser>;
}

export async function logoutApi(token: string): Promise<void> {
  await requestJson<{ message: string }>('/auth/logout', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
}

export async function listUploadedPapersApi(
  token: string,
  options?: { sort?: 'uploaded_at' | 'last_viewed_at'; limit?: number },
): Promise<UploadedPaper[]> {
  const params = new URLSearchParams();
  if (options?.sort) params.set('sort', options.sort);
  if (options?.limit) params.set('limit', String(options.limit));
  const query = params.toString();

  const response = await fetch(`${apiBaseUrl}/papers/${query ? `?${query}` : ''}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorBody?.detail ?? `Request failed with status ${response.status}`);
  }

  return response.json() as Promise<UploadedPaper[]>;
}

export async function getPaperApi(token: string, paperId: number | string): Promise<UploadedPaper> {
  const response = await fetch(`${apiBaseUrl}/papers/${paperId}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorBody?.detail ?? `Request failed with status ${response.status}`);
  }

  return response.json() as Promise<UploadedPaper>;
}

export async function deletePaperApi(token: string, paperId: number | string): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/papers/${paperId}`, {
    method: 'DELETE',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorBody?.detail ?? `Request failed with status ${response.status}`);
  }
}