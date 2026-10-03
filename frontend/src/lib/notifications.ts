export type NotificationItem = {
  id: number;
  user_id: number;
  source: string;
  external_id: string;
  title: string;
  message: string;
  external_url: string | null;
  pdf_url: string | null;
  categories: string[];
  recommendation_score: number | null;
  is_read: boolean;
  created_at: string;
};

export type NotificationListResponse = {
  notifications: NotificationItem[];
  unread_count: number;
};

export type NotificationJobResponse = {
  created_count: number;
  skipped_count: number;
  warnings: string[];
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

export function listNotificationsApi(token: string, limit = 20): Promise<NotificationListResponse> {
  return requestJson<NotificationListResponse>(`/notifications?limit=${limit}`, token);
}

export function markNotificationReadApi(token: string, notificationId: number): Promise<NotificationItem> {
  return requestJson<NotificationItem>(`/notifications/${notificationId}/read`, token, { method: 'POST' });
}

export function runNotificationCheckApi(token: string): Promise<NotificationJobResponse> {
  return requestJson<NotificationJobResponse>('/notifications/check', token, { method: 'POST' });
}
