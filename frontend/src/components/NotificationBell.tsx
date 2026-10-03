import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  listNotificationsApi,
  markNotificationReadApi,
  runNotificationCheckApi,
  type NotificationItem,
} from '../lib/notifications';

function timeLabel(value: string): string {
  const elapsedMinutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60000));
  if (elapsedMinutes < 1) return 'now';
  if (elapsedMinutes < 60) return `${elapsedMinutes}m`;
  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) return `${elapsedHours}h`;
  return `${Math.floor(elapsedHours / 24)}d`;
}

export default function NotificationBell() {
  const { token } = useAuth();
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');

  async function refresh() {
    if (!token) return;
    try {
      const response = await listNotificationsApi(token);
      setNotifications(response.notifications);
      setUnreadCount(response.unread_count);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Unable to load alerts');
    }
  }

  useEffect(() => {
    void refresh();
    if (!token) return;
    const intervalId = window.setInterval(() => void refresh(), 60000);
    return () => window.clearInterval(intervalId);
  }, [token]);

  async function markRead(notification: NotificationItem) {
    if (!token || notification.is_read) return;
    try {
      await markNotificationReadApi(token, notification.id);
      setNotifications((current) => current.map((item) => item.id === notification.id ? { ...item, is_read: true } : item));
      setUnreadCount((current) => Math.max(0, current - 1));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Unable to update alert');
    }
  }

  async function checkNow() {
    if (!token) return;
    setChecking(true);
    setError('');
    try {
      await runNotificationCheckApi(token);
      await refresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Unable to check for new papers');
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        aria-label="Open paper alerts"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="relative rounded-full px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
      >
        Alerts
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 min-w-5 rounded-full bg-brand-600 px-1.5 py-0.5 text-center text-[10px] font-bold text-white">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-12 z-30 w-[min(22rem,calc(100vw-2rem))] rounded-2xl border border-slate-200 bg-white p-4 shadow-xl">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-900">Paper alerts</h2>
              <p className="text-xs text-slate-500">New research matched to your interests.</p>
            </div>
            <button type="button" onClick={() => void checkNow()} disabled={checking} className="rounded-full border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50">
              {checking ? 'Checking...' : 'Check now'}
            </button>
          </div>

          {error && <p className="mt-3 text-xs text-rose-600">{error}</p>}
          {notifications.length === 0 && !error && <p className="mt-4 text-sm text-slate-500">No alerts yet.</p>}
          <div className="mt-3 max-h-80 space-y-2 overflow-y-auto">
            {notifications.map((notification) => (
              <article key={notification.id} className={`rounded-xl border p-3 ${notification.is_read ? 'border-slate-100 bg-slate-50' : 'border-brand-100 bg-brand-50/40'}`}>
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-sm font-medium text-slate-900">{notification.title}</h3>
                  <span className="shrink-0 text-[11px] text-slate-400">{timeLabel(notification.created_at)}</span>
                </div>
                <p className="mt-1 text-xs leading-5 text-slate-600">{notification.message}</p>
                <div className="mt-2 flex items-center gap-3">
                  {notification.external_url && <a href={notification.external_url} target="_blank" rel="noreferrer" className="text-xs font-medium text-brand-600 hover:text-brand-700">Open paper</a>}
                  {!notification.is_read && <button type="button" onClick={() => void markRead(notification)} className="text-xs font-medium text-slate-500 hover:text-slate-800">Mark read</button>}
                </div>
              </article>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
