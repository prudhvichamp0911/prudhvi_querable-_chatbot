"use client";

import { useCallback, useEffect, useState } from "react";
import { useNav, useThread, useThreadList } from "@openuidev/react-ui";
import { MessageSquarePlus, RefreshCw, TriangleAlert } from "lucide-react";

import { authFetch, errorMessage } from "@/lib/api";

/** GET a JSON endpoint through the authenticated /api rewrite. */
export function useApi<T>(url: string | null) {
  const [nonce, setNonce] = useState(0);
  const key = url ? `${url}#${nonce}` : null;
  // The last finished request; `loading` is derived from whether it matches `key`.
  const [state, setState] = useState<{ key: string | null; data: T | null; error: string | null }>({
    key: null,
    data: null,
    error: null,
  });

  useEffect(() => {
    if (!url || !key) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await authFetch(url);
        if (!response.ok) throw new Error(await errorMessage(response, "The request failed."));
        const body = (await response.json()) as T;
        if (!cancelled) setState({ key, data: body, error: null });
      } catch (err) {
        if (!cancelled) {
          setState((prev) => ({ key, data: prev.data, error: err instanceof Error ? err.message : "The request failed." }));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [url, key]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const loading = key !== null && state.key !== key;
  return { data: state.data, error: loading ? null : state.error, loading, reload };
}

/** Start a fresh conversation with a prompt, from any tool page. */
export function useAsk() {
  const { navigate } = useNav();
  const switchToNewThread = useThreadList((s) => s.switchToNewThread);
  const processMessage = useThread((s) => s.processMessage);
  return useCallback(
    (prompt: string) => {
      navigate(undefined);
      switchToNewThread();
      // Let the thread view mount before the message is sent.
      window.setTimeout(() => void processMessage({ role: "user", content: prompt }), 60);
    },
    [navigate, switchToNewThread, processMessage],
  );
}

export function ToolPage({
  icon,
  eyebrow,
  title,
  description,
  actions,
  children,
}: {
  icon: React.ReactNode;
  eyebrow: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="qc-tool-page">
      <div className="qc-tool-page__inner">
        <header className="qc-tool-page__head">
          <div>
            <p className="qc-eyebrow">
              {icon} {eyebrow}
            </p>
            <h1>{title}</h1>
            {description && <p className="qc-tool-page__description">{description}</p>}
          </div>
          {actions && <div className="qc-tool-page__actions">{actions}</div>}
        </header>
        {children}
      </div>
    </div>
  );
}

export function LoadState({ loading, error, onRetry }: { loading: boolean; error: string | null; onRetry?: () => void }) {
  if (error) {
    return (
      <div className="qc-state qc-state--error" role="alert">
        <TriangleAlert size={18} />
        <span>{error}</span>
        {onRetry && (
          <button type="button" className="qc-ghost-button" onClick={onRetry}>
            <RefreshCw size={13} /> Retry
          </button>
        )}
      </div>
    );
  }
  if (loading) {
    return (
      <div className="qc-skeleton-grid" aria-busy="true" aria-label="Loading">
        {Array.from({ length: 6 }, (_, i) => (
          <span key={i} className="qc-skeleton" />
        ))}
      </div>
    );
  }
  return null;
}

export function AskButton({ prompt, label = "Ask in chat" }: { prompt: string; label?: string }) {
  const ask = useAsk();
  return (
    <button type="button" className="qc-ghost-button" onClick={() => ask(prompt)} title={prompt}>
      <MessageSquarePlus size={13} /> {label}
    </button>
  );
}
