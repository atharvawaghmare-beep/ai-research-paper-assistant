import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import CitationList from '../components/CitationList';
import CitationsPanel from '../components/CitationsPanel';
import ConceptExplainPanel from '../components/ConceptExplainPanel';
import SummaryPanel from '../components/SummaryPanel';
import { useAuth } from '../context/AuthContext';
import { deletePaperApi, getPaperApi, type UploadedPaper } from '../lib/auth';
import {
  getChatSessionApi,
  listChatSessionsApi,
  sendChatMessageApi,
  type ChatMessage,
} from '../lib/chat';

const TERMINAL_STATUSES = new Set(['ready', 'failed']);
const PAPER_POLL_INTERVAL_MS = 3000;

const PROCESSING_LABELS: Record<string, string> = {
  uploaded: 'Queued for processing',
  chunking: 'Chunking the paper...',
  embedding: 'Generating embeddings...',
};

const TABS = [
  { value: 'chat', label: 'Chat' },
  { value: 'summary', label: 'Summary' },
  { value: 'explain', label: 'Explain a concept' },
  { value: 'citations', label: 'Citations' },
] as const;

type Tab = (typeof TABS)[number]['value'];

let tempMessageId = -1;

export default function PaperDetailPage() {
  const { paperId } = useParams<{ paperId: string }>();
  const { token } = useAuth();
  const navigate = useNavigate();

  const [activeTab, setActiveTab] = useState<Tab>('chat');

  const [paper, setPaper] = useState<UploadedPaper | null>(null);
  const [paperError, setPaperError] = useState('');
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const [sessionId, setSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [sessionPapers, setSessionPapers] = useState<UploadedPaper[]>([]);

  const [inputValue, setInputValue] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');

  const chatScrollRef = useRef<HTMLDivElement | null>(null);

  // Load paper details, and keep polling while it's still processing so the
  // user isn't stuck on a stale "queued" state if they opened this page early.
  useEffect(() => {
    if (!token || !paperId) return;
    let cancelled = false;

    async function loadPaper() {
      try {
        const data = await getPaperApi(token!, paperId!);
        if (!cancelled) setPaper(data);
      } catch (error) {
        if (!cancelled) setPaperError(error instanceof Error ? error.message : 'Unable to load this paper');
      }
    }

    void loadPaper();
    const intervalId = window.setInterval(() => {
      if (paper && TERMINAL_STATUSES.has(paper.processing_status)) return;
      void loadPaper();
    }, PAPER_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, paperId, paper?.processing_status]);

  // Resume the most recent chat session for this paper, if one exists.
  useEffect(() => {
    if (!token || !paperId) return;
    let cancelled = false;

    async function loadHistory() {
      try {
        const sessions = await listChatSessionsApi(token!, paperId!);
        if (cancelled) return;
        if (sessions.length === 0) {
          setHistoryLoading(false);
          return;
        }
        const latest = sessions[0];
        const full = await getChatSessionApi(token!, paperId!, latest.id);
        if (cancelled) return;
        setSessionId(full.id);
        setMessages(full.messages);
        setSessionPapers(full.papers);
      } catch {
        // No existing conversation to resume — start fresh silently.
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    }

    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, [token, paperId]);

  // Scroll only the message container itself, not the whole window — the page
  // as a whole can be taller than the viewport, and `scrollIntoView` on a
  // bottom-anchored element would bubble up to the window and yank the entire
  // page down, cutting off the header above the chat panel.
  useEffect(() => {
    if (activeTab === 'chat' && chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [messages, sending, activeTab]);

  const isPaperReady = paper?.processing_status === 'ready';
  const canSend = Boolean(isPaperReady && token && inputValue.trim() && !sending);

  async function handleSend(event: FormEvent) {
    event.preventDefault();
    if (!canSend || !token || !paperId) return;

    const question = inputValue.trim();
    setInputValue('');
    setSendError('');

    const optimisticMessage: ChatMessage = {
      id: tempMessageId--,
      session_id: sessionId ?? 0,
      message_index: messages.length,
      role: 'user',
      content: question,
      citations: null,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimisticMessage]);
    setSending(true);

    const isNewSession = sessionId === null;

    try {
      const result = await sendChatMessageApi(token, paperId, question, sessionId);
      setSessionId(result.session_id);
      setMessages((current) => [
        ...current.filter((message) => message.id !== optimisticMessage.id),
        result.user_message,
        result.assistant_message,
      ]);

      // The turn response doesn't carry the session's paper list — only relevant
      // the first time a session is created, so the "Comparing N papers" banner
      // (still shown for sessions started via the /compare page) has data.
      if (isNewSession) {
        try {
          const full = await getChatSessionApi(token, paperId, result.session_id);
          setSessionPapers(full.papers);
        } catch {
          // Non-critical — the chat itself already succeeded, just skip the paper badges.
        }
      }
    } catch (error) {
      setSendError(error instanceof Error ? error.message : 'Failed to get a response');
    } finally {
      setSending(false);
    }
  }

  const processingLabel = useMemo(() => {
    if (!paper) return null;
    return PROCESSING_LABELS[paper.processing_status] ?? null;
  }, [paper]);

  async function handleDelete() {
    if (!token || !paperId) return;
    setDeleting(true);
    setDeleteError('');

    try {
      await deletePaperApi(token, paperId);
      navigate('/dashboard', { replace: true });
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : 'Failed to delete paper');
      setDeleting(false);
    }
  }

  return (
    <section className="flex h-[calc(100vh-14rem)] flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <Link to="/dashboard" className="text-sm font-medium text-brand-600 hover:text-brand-700">
            ← Back to dashboard
          </Link>
          <h2 className="mt-1 truncate text-2xl font-semibold text-slate-900">{paper?.title ?? 'Loading paper...'}</h2>
        </div>
        {paper && (
          <div className="flex shrink-0 items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-500">
              {paper.processing_status}
            </span>
            {confirmingDelete ? (
              <>
                <button
                  type="button"
                  onClick={() => void handleDelete()}
                  disabled={deleting}
                  className="rounded-full bg-rose-600 px-3.5 py-1.5 text-sm font-medium text-white transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {deleting ? 'Deleting...' : 'Confirm delete'}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmingDelete(false)}
                  disabled={deleting}
                  className="rounded-full px-3.5 py-1.5 text-sm font-medium text-slate-500 transition hover:bg-slate-100"
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmingDelete(true)}
                className="rounded-full px-3.5 py-1.5 text-sm font-medium text-slate-500 transition hover:bg-rose-50 hover:text-rose-600"
              >
                Delete paper
              </button>
            )}
          </div>
        )}
      </div>

      {deleteError && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{deleteError}</div>
      )}

      {paperError && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{paperError}</div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setActiveTab(tab.value)}
            className={[
              'rounded-full px-4 py-2 text-sm font-medium transition',
              activeTab === tab.value
                ? 'bg-slate-900 text-white'
                : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50',
            ].join(' ')}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card">
        {activeTab === 'chat' && (
          <>
            {sessionPapers.length > 1 && (
              <div className="border-b border-slate-200 px-5 py-3">
                <p className="mb-2 text-xs font-medium uppercase tracking-[0.1em] text-slate-500">
                  Comparing {sessionPapers.length} papers
                </p>
                <div className="flex flex-wrap gap-2">
                  {sessionPapers.map((sessionPaper) => (
                    <span
                      key={sessionPaper.id}
                      className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600"
                    >
                      {sessionPaper.title}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div ref={chatScrollRef} className="flex-1 overflow-y-auto px-5 py-6">
              {!isPaperReady && paper ? (
                <div className="grid h-full place-items-center text-center">
                  <div>
                    <p className="text-sm font-medium text-slate-800">{processingLabel ?? 'This paper is not ready for chat yet.'}</p>
                    <p className="mt-2 text-sm text-slate-500">The chat will unlock automatically once processing finishes.</p>
                  </div>
                </div>
              ) : historyLoading ? (
                <div className="grid h-full place-items-center text-sm text-slate-500">Loading conversation...</div>
              ) : messages.length === 0 ? (
                <div className="grid h-full place-items-center text-center">
                  <div className="max-w-sm">
                    <p className="text-sm font-medium text-slate-800">Ask anything about this paper</p>
                    <p className="mt-2 text-sm text-slate-500">
                      Answers are grounded in the paper's actual content, with page citations you can expand below each response.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  {messages.map((message) => (
                    <div key={message.id} className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                      <div className={message.role === 'user' ? 'max-w-[75%]' : 'max-w-[85%]'}>
                        <div
                          className={[
                            'rounded-2xl px-4 py-3 text-sm leading-6 whitespace-pre-wrap',
                            message.role === 'user'
                              ? 'bg-brand-600 text-white'
                              : 'border border-slate-200 bg-slate-50 text-slate-800',
                          ].join(' ')}
                        >
                          {message.content}
                        </div>

                        {message.role === 'assistant' && (
                          <CitationList citations={message.citations} idPrefix={String(message.id)} />
                        )}
                      </div>
                    </div>
                  ))}

                  {sending && (
                    <div className="flex justify-start">
                      <div className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">
                        <span className="flex gap-1">
                          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500" />
                          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:150ms]" />
                          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500 [animation-delay:300ms]" />
                        </span>
                        Thinking...
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {sendError && (
              <div className="mx-5 mb-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">
                {sendError}
              </div>
            )}

            <form onSubmit={handleSend} className="flex items-end gap-3 border-t border-slate-200 p-4">
              <textarea
                value={inputValue}
                onChange={(event) => setInputValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    void handleSend(event);
                  }
                }}
                disabled={!isPaperReady || sending}
                placeholder={isPaperReady ? 'Ask a question about this paper...' : 'Waiting for processing to finish...'}
                rows={2}
                className="flex-1 resize-none rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-100 disabled:opacity-60"
              />
              <button
                type="submit"
                disabled={!canSend}
                className="rounded-full bg-brand-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {sending ? 'Sending...' : 'Send'}
              </button>
            </form>
          </>
        )}

        {activeTab === 'summary' && paperId && <SummaryPanel paperId={paperId} isPaperReady={Boolean(isPaperReady)} />}

        {activeTab === 'explain' && paperId && (
          <ConceptExplainPanel paperId={paperId} isPaperReady={Boolean(isPaperReady)} />
        )}

        {activeTab === 'citations' && paperId && (
          <CitationsPanel paperId={paperId} isPaperReady={Boolean(isPaperReady)} />
        )}
      </div>
    </section>
  );
}
