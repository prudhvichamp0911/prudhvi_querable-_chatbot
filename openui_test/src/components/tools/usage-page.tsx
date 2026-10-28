"use client";

import { Activity, RefreshCw } from "lucide-react";

import { BarList } from "@/components/charts";
import { LoadState, ToolPage, useApi } from "@/components/tools/shared";
import { formatValue } from "@/lib/geo";

type Metrics = {
  requests: number;
  errors: number;
  fallbacks: number;
  latency_p50_s: number | null;
  latency_p95_s: number | null;
  latency_mean_s: number | null;
  total_tokens: number;
  total_cost_usd: number;
  by_route: Record<string, number>;
};

const ROUTES: Record<string, string> = {
  database_query: "Database questions",
  general_chat: "General questions",
  browser_task: "Browser tasks",
  blocked: "Blocked by guardrails",
};

const seconds = (value: number | null) => (value == null ? "—" : `${value.toFixed(1)}s`);

export function UsagePage() {
  const { data, error, loading, reload } = useApi<Metrics>("/api/metrics");
  const tiles = data
    ? [
        { label: "Requests", value: formatValue(data.requests), hint: "since the server started" },
        { label: "Median latency", value: seconds(data.latency_p50_s), hint: `p95 ${seconds(data.latency_p95_s)}` },
        { label: "Tokens", value: formatValue(data.total_tokens), hint: "prompt + completion" },
        { label: "Cost", value: `$${data.total_cost_usd.toFixed(4)}`, hint: "OpenRouter spend" },
        {
          label: "Success rate",
          value: data.requests ? `${(((data.requests - data.errors) / data.requests) * 100).toFixed(0)}%` : "—",
          hint: `${data.errors} errors · ${data.fallbacks} fallbacks`,
        },
      ]
    : [];

  return (
    <ToolPage
      icon={<Activity size={13} />}
      eyebrow="Usage & health"
      title="How the assistant is performing"
      description="Latency, tokens and cost for recent requests, and how questions were routed."
      actions={
        <button type="button" className="qc-ghost-button" onClick={reload}>
          <RefreshCw size={13} /> Refresh
        </button>
      }
    >
      <LoadState loading={loading && !data} error={error} onRetry={reload} />
      {data && (
        <>
          <section className="qc-kpi-row">
            {tiles.map((tile) => (
              <article key={tile.label} className="qc-kpi">
                <span className="qc-kpi__label">{tile.label}</span>
                <span className="qc-kpi__value">{tile.value}</span>
                <span className="qc-kpi__hint">{tile.hint}</span>
              </article>
            ))}
          </section>
          <section className="qc-tile">
            <h2 className="qc-tile__title">Questions by route</h2>
            {Object.keys(data.by_route).length ? (
              <BarList rows={Object.entries(data.by_route).map(([route, value]) => ({ label: ROUTES[route] ?? route, value }))} />
            ) : (
              <p className="qc-muted">No requests yet — ask something in the chat.</p>
            )}
          </section>
        </>
      )}
    </ToolPage>
  );
}
