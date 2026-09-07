import { useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '../context/AuthContext';

type Toast = {
  id: string;
  kind: 'success' | 'error' | 'info';
  message: string;
};

type QueueItem = {
  id: string;
  file: File;
  progress: number;
  status: 'queued' | 'uploading' | 'success' | 'error';
  message?: string;
};

type UploadedPaperResponse = {
  id: number;
  title: string;
  original_filename: string;
  processing_status: string;
  uploaded_at: string;
  file_size_bytes: number | null;
};

type PdfUploadDropzoneProps = {
  onUploaded?: () => void;
};

const MAX_FILE_SIZE_MB = 25;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

function humanFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isPdf(file: File) {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
}

function uploadPdf(file: File, token: string, onProgress: (progress: number) => void): Promise<UploadedPaperResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE_URL}/papers/upload`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      const body = xhr.responseText ? (JSON.parse(xhr.responseText) as UploadedPaperResponse) : null;

      if (xhr.status >= 200 && xhr.status < 300 && body) {
        resolve(body);
        return;
      }

      const errorMessage = body && typeof body === 'object' && 'detail' in body ? String((body as { detail?: unknown }).detail) : `Upload failed with status ${xhr.status}`;
      reject(new Error(errorMessage));
    };

    xhr.onerror = () => {
      reject(new Error('Network error while uploading PDF'));
    };

    const formData = new FormData();
    formData.append('file', file);
    xhr.send(formData);
  });
}

export default function PdfUploadDropzone({ onUploaded }: PdfUploadDropzoneProps) {
  const { token } = useAuth();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const hasQueuedFiles = queue.some((item) => item.status === 'queued' || item.status === 'error');

  useEffect(() => {
    return () => {
      toasts.forEach((toast) => window.clearTimeout(Number(toast.id)));
    };
  }, [toasts]);

  function pushToast(kind: Toast['kind'], message: string) {
    const id = window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== String(id)));
    }, 4000);

    setToasts((current) => [...current, { id: String(id), kind, message }]);
  }

  function addFiles(files: FileList | File[]) {
    const nextQueue: QueueItem[] = [];

    Array.from(files).forEach((file) => {
      if (!isPdf(file)) {
        pushToast('error', `${file.name} was skipped because only PDF files are allowed.`);
        return;
      }

      if (file.size > MAX_FILE_SIZE_BYTES) {
        pushToast('error', `${file.name} exceeds the ${MAX_FILE_SIZE_MB} MB limit.`);
        return;
      }

      nextQueue.push({
        id: `${file.name}-${file.size}-${crypto.randomUUID()}`,
        file,
        progress: 0,
        status: 'queued',
      });
    });

    if (nextQueue.length > 0) {
      setQueue((current) => [...current, ...nextQueue]);
      pushToast('info', `${nextQueue.length} PDF${nextQueue.length === 1 ? '' : 's'} added to the queue.`);
    }
  }

  async function handleUpload() {
    if (!token) {
      pushToast('error', 'You must be signed in to upload papers.');
      return;
    }

    const uploadTargets = queue.filter((item) => item.status === 'queued' || item.status === 'error');
    if (uploadTargets.length === 0) {
      pushToast('info', 'Add one or more PDF files first.');
      return;
    }

    setIsUploading(true);

    for (const item of uploadTargets) {
      setQueue((current) => current.map((entry) => (entry.id === item.id ? { ...entry, status: 'uploading', progress: 0, message: undefined } : entry)));

      try {
        const result = await uploadPdf(item.file, token, (progress) => {
          setQueue((current) => current.map((entry) => (entry.id === item.id ? { ...entry, progress } : entry)));
        });

        setQueue((current) =>
          current.map((entry) =>
            entry.id === item.id ? { ...entry, status: 'success', progress: 100, message: result.title } : entry,
          ),
        );
        onUploaded?.();
        pushToast('success', `${result.original_filename} uploaded successfully.`);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Upload failed';
        setQueue((current) => current.map((entry) => (entry.id === item.id ? { ...entry, status: 'error', message } : entry)));
        pushToast('error', `${item.file.name}: ${message}`);
      }
    }

    setIsUploading(false);
    setQueue((current) => current.filter((entry) => entry.status !== 'success'));
  }

  function clearQueue() {
    setQueue([]);
    pushToast('info', 'Upload queue cleared.');
  }

  const queueSummary = useMemo(() => {
    const total = queue.length;
    const uploading = queue.filter((item) => item.status === 'uploading').length;
    const success = queue.filter((item) => item.status === 'success').length;
    return { total, uploading, success };
  }, [queue]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-1">
          <h3 className="text-lg font-semibold text-slate-900">Upload a paper</h3>
        </div>

        {queueSummary.total > 0 && (
          <div className="flex gap-4 text-xs text-slate-500">
            <span>{queueSummary.total} queued</span>
            <span>{queueSummary.uploading} uploading</span>
            <span>{queueSummary.success} done</span>
          </div>
        )}
      </div>

      <div
        className={[
          'mt-4 rounded-xl border border-dashed p-6 transition',
          isDragging ? 'border-brand-400 bg-brand-50' : 'border-slate-300 bg-slate-50',
        ].join(' ')}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          addFiles(event.dataTransfer.files);
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={(event) => {
            if (event.target.files) {
              addFiles(event.target.files);
              event.target.value = '';
            }
          }}
        />

        <div className="flex flex-col items-start gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-sm font-medium text-slate-800">Drag and drop PDFs here</p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
            >
              Choose files
            </button>
            <button
              type="button"
              onClick={() => void handleUpload()}
              disabled={isUploading || !hasQueuedFiles}
              className="rounded-full bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isUploading ? 'Uploading...' : 'Upload PDFs'}
            </button>
            {queue.length > 0 && (
              <button
                type="button"
                onClick={clearQueue}
                className="rounded-full px-4 py-2 text-sm font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      </div>

      {queue.length > 0 && (
        <div className="mt-4 grid gap-3">
          {queue.map((item) => (
            <article key={item.id} className="rounded-xl border border-slate-200 p-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-slate-800">{item.file.name}</p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {humanFileSize(item.file.size)} · {item.status}
                    {item.message ? ` · ${item.message}` : ''}
                  </p>
                </div>
                <div className="text-right text-xs text-slate-500">{item.progress}%</div>
              </div>

              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
                <div
                  className={[
                    'h-full rounded-full transition-all duration-300',
                    item.status === 'error' ? 'bg-rose-500' : item.status === 'success' ? 'bg-emerald-500' : 'bg-brand-500',
                  ].join(' ')}
                  style={{ width: `${item.progress}%` }}
                />
              </div>
            </article>
          ))}
        </div>
      )}

      <div className="mt-4 space-y-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={[
              'flex items-start justify-between gap-3 rounded-xl border px-4 py-2.5 text-sm',
              toast.kind === 'success'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : toast.kind === 'error'
                ? 'border-rose-200 bg-rose-50 text-rose-800'
                : 'border-brand-100 bg-brand-50 text-brand-800',
            ].join(' ')}
          >
            <p>{toast.message}</p>
            <button
              type="button"
              onClick={() => setToasts((current) => current.filter((entry) => entry.id !== toast.id))}
              className="text-xs font-medium text-current/70 hover:text-current"
            >
              Dismiss
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}