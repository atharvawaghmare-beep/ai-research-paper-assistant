import { FormEvent, useEffect, useState } from 'react';
import CitationList from '../components/CitationList';
import { useAuth } from '../context/AuthContext';
import { listUploadedPapersApi, type UploadedPaper } from '../lib/auth';
import { sendChatMessageApi, type ChatMessage } from '../lib/chat';
import { comparePapersApi, type PaperCompareEntry } from '../lib/paperTools';

const MIN_COMPARE = 2;
const MAX_COMPARE = 5;

let tempMessageId = -1;

export default function ComparePage() {
  const { token } = useAuth();

  const [papers, setPapers] = useState<UploadedPaper[]>([]);
  const [loadingPapers, setLoadingPapers] = useState(true);
  const [papersError, setPapersError] = useState('');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  const [compareEntries, setCompareEntries] = useState<PaperCompareEntry[]>([]);
  const [comparedIds, setComparedIds] = useState<number[]>([]);
  const [loadingCompare, setLoadingCompare] = useState(false);
  const [compareError, setCompareError] = useState('');

  const [sessionId, setSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    listUploadedPapersApi(token)
      .then((result) => {
        if (cancelled) return;
        setPapers(result.filter((paper) => paper.processing_status === 'ready'));
      })
      .catch((error) => {
        if (!cancelled) setPapersError(error instanceof Error ? error.message : 'Unable to load your papers');
      })
      .finally(() => {
        if (!cancelled) setLoadingPapers(false);
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  function toggle(id: number) {
    setSelectedIds((current) => {
      if (current.includes(id)) return current.filter((existing) => existing !== id);
      if (current.length >= MAX_COMPARE) return current;
      return [...current, id];
    });
  }

  async function handleCompare() {
    if (!token || selectedIds.length < MIN_COMPARE) return;
    setLoadingCompare(true);
    setCompareError('');
    setSessionId(null);
    setMessages([]);
    setSendError('');

    try {
      const result = await comparePapersApi(token, selectedIds);
      setCompareEntries(result.papers);
      setComparedIds([...selectedIds]);
    } catch (error) {
      setCompareError(error instanceof Error ? error.message : 'Failed to load summaries');
    } finally {
      setLoadingCompare(false);
    }
  }

  async function handleSend(event: FormEvent) {
    event.preventDefault();
    if (!token || comparedIds.length < MIN_COMPARE || !inputValue.trim() || sending) return;

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

    try {
      // The chat endpoint is anchored under one paper's URL, plus additional paper
      // ids for the rest (Phase 4 multi-paper Q&A) — no new retrieval logic here,
      // just picking the first selected paper as the anchor.
      const [anchorId, ...otherIds] = comparedIds;
      const result = await sendChatMessageApi(token, anchorId, question, sessionId, otherIds);
      setSessionId(result.session_id);
      setMessages((current) => [
        ...current.filter((message) => message.id !== optimisticMessage.id),
        result.user_message,
        result.assistant_message,
      ]);
    } catch (error) {
      setSendError(error instanceof Error ? error.message : 'Failed to get a response');
      setMessages((current) => current.filter((message) => message.id !== optimisticMessage.id));
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-slate-900">Compare papers</h1>
        <p className="text-sm text-slate-500">
          Select {MIN_COMPARE}-{MAX_COMPARE} papers to see their summaries side by side, then ask a question that
          draws on all of them at once.
        </p>
      </header>

      <section className="space-y-3">
        {loadingPapers ? (
          <p className="text-sm text-slate-500">Loading your papers...</p>
        ) : papersError ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">{papersError}</div>
        ) : papers.length < MIN_COMPARE ? (
          <p className="text-sm text-slate-500">
            You need at least {MIN_COMPARE} papers finished processing before you can compare them.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {papers.map((paper) => {
                const isSelected = selectedIds.includes(paper.id);
                return (
                  <button
                    key={paper.id}
                    type="button"
                    onClick={() => toggle(paper.id)}
                    disabled={!isSelected && selectedIds.length >= MAX_COMPARE}
                    className={[
                      'rounded-full border px-3.5 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50',
                      isSelected
                        ? 'border-brand-600 bg-brand-600 text-white'
                        : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50',
                    ].join(' ')}
                  >
                    {paper.title}
                  </button>
                );
              })}
            </div>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => void handleCompare()}
                disabled={selectedIds.length < MIN_COMPARE || loadingCompare}
                className="rounded-full bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loadingCompare ? 'Loading summaries...' : `Compare ${selectedIds.length || ''}`.trim()}
              </button>
              <span className="text-xs text-slate-400">
                {selectedIds.length}/{MAX_COMPARE} selected
              </span>
            </div>
          </>
        )}

        {compareError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">{compareError}</div>
        )}
      </section>

      {compareEntries.length > 0 && (
        <>
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {compareEntries.map((entry) => (
              <article key={entry.paper.id} className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
                <h3 className="text-sm font-semibold text-slate-900">{entry.paper.title}</h3>
                <div className="mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap text-sm leading-6 text-slate-600">
                  {entry.summary}
                </div>
              </article>
            ))}
          </section>

          <section className="flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card">
            <div className="border-b border-slate-200 px-5 py-3">
              <p className="text-sm font-medium text-slate-800">Ask a comparison question</p>
              <p className="text-xs text-slate-500">
                Answers cite which paper each claim came from — expand a citation below the answer to check it.
              </p>
            </div>

            <div className="max-h-96 overflow-y-auto px-5 py-6">
              {messages.length === 0 ? (
                <p className="text-center text-sm text-slate-500">
                  e.g. "What datasets does each paper evaluate on?" or "How do their approaches differ?"
                </p>
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
                disabled={sending}
                placeholder="Ask a question about the selected papers..."
                rows={2}
                className="flex-1 resize-none rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-100 disabled:opacity-60"
              />
              <button
                type="submit"
                disabled={sending || !inputValue.trim()}
                className="rounded-full bg-brand-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {sending ? 'Sending...' : 'Send'}
              </button>
            </form>
          </section>
        </>
      )}
    </section>
  );
}
