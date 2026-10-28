"use client";

import { useState } from "react";
import { BarChart3, Crown, Globe2, Lightbulb, RefreshCw, Sparkles, TrendingDown, TrendingUp } from "lucide-react";

import { BarList, Donut, TrendChart, type Row } from "@/components/charts";
import { GeoInsightList } from "@/components/geo-panel";
import { WorldGlobe } from "@/components/world-globe";
import { AskButton, LoadState, ToolPage, useApi } from "@/components/tools/shared";
import { formatValue, metricFormat, type GeoPayload, type InsightCard, type ValueFormat } from "@/lib/geo";

type Kpi = { id: string; label: string; value: number; format: ValueFormat; hint: string };
type Panel = { id: string; title: string; kind: "bar" | "donut" | "line"; metric: string; format: ValueFormat; rows: Row[] };
type Overview = {
  kpis: Kpi[];
  panels: Panel[];
  maps: (GeoPayload & { id: string; title: string })[];
  headlines: InsightCard[];
};

function headlineIcon(card: InsightCard) {
  if (card.kind === "trend") return card.value.startsWith("-") ? <TrendingDown size={16} /> : <TrendingUp size={16} />;
  if (card.kind === "geo") return <Globe2 size={16} />;
  if (card.kind === "leader") return <Crown size={16} />;
  return <Sparkles size={16} />;
}

export function InsightsPage() {
  const { data, error, loading, reload } = useApi<Overview>("/api/insights/overview");
  const [mapId, setMapId] = useState<string | null>(null);
  const activeMap = data?.maps.find((m) => m.id === mapId) ?? [...(data?.maps ?? [])].sort((a, b) => b.places.length - a.places.length)[0];

  return (
    <ToolPage
      icon={<Lightbulb size={13} />}
      eyebrow="Insights studio"
      title="What your data is saying"
      description="Live KPIs, charts and auto-detected patterns computed straight from MongoDB — no model guesses."
      actions={
        <button type="button" className="qc-ghost-button" onClick={reload}>
          <RefreshCw size={13} /> Refresh
        </button>
      }
    >
      <LoadState loading={loading && !data} error={error} onRetry={reload} />
      {data && (
        <>
          <section className="qc-kpi-row" aria-label="Key metrics">
            {data.kpis.map((kpi, index) => (
              <article key={kpi.id} className="qc-kpi" style={{ animationDelay: `${index * 40}ms` }}>
                <span className="qc-kpi__label">{kpi.label}</span>
                <span className="qc-kpi__value">{formatValue(kpi.value, kpi.format)}</span>
                <span className="qc-kpi__hint">{kpi.hint}</span>
              </article>
            ))}
          </section>

          {data.headlines.length > 0 && (
            <section className="qc-headlines" aria-label="Auto-detected insights">
              <h2 className="qc-section-title">
                <Sparkles size={15} /> Auto-detected insights
              </h2>
              <div className="qc-headlines__grid">
                {data.headlines.map((card, index) => (
                  <article key={`${card.source}-${card.title}`} className="qc-headline" style={{ animationDelay: `${index * 50}ms` }}>
                    <span className="qc-headline__icon">{headlineIcon(card)}</span>
                    <div>
                      <p className="qc-headline__title">
                        {card.title} {card.value && <b>{card.value}</b>}
                      </p>
                      <p className="qc-headline__detail">
                        {card.detail} · <span>{card.source}</span>
                      </p>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}

          {activeMap && (
            <section className="qc-tile qc-tile--map">
              <header className="qc-tile__head">
                <h2 className="qc-tile__title">
                  <Globe2 size={15} /> {activeMap.title}
                </h2>
                <div className="qc-segmented" role="tablist">
                  {data.maps.map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      role="tab"
                      aria-selected={m.id === activeMap.id}
                      className={m.id === activeMap.id ? "is-active" : ""}
                      onClick={() => setMapId(m.id)}
                    >
                      {m.title.split(" by ")[0]}
                    </button>
                  ))}
                </div>
              </header>
              <div className="qc-map-split">
                <WorldGlobe key={activeMap.id} places={activeMap.places} regions={activeMap.regions} metric={activeMap.metric} initialView="world" />
                <div className="qc-map-split__side">
                  <BarList
                    rows={activeMap.places.map((p) => ({ label: p.name, value: p.value ?? 0 }))}
                    format={metricFormat(activeMap.metric)}
                    max={8}
                  />
                  <GeoInsightList insights={activeMap.insights.slice(0, 3)} />
                </div>
              </div>
            </section>
          )}

          <section className="qc-panel-grid">
            {data.panels.map((panel) => (
              <article key={panel.id} className={`qc-tile ${panel.kind === "line" ? "qc-tile--wide" : ""}`}>
                <header className="qc-tile__head">
                  <h2 className="qc-tile__title">
                    <BarChart3 size={15} /> {panel.title}
                  </h2>
                  <AskButton prompt={`Analyse ${panel.title.toLowerCase()} and explain the key drivers`} label="Ask" />
                </header>
                {panel.kind === "bar" && <BarList rows={panel.rows} format={panel.format} max={8} />}
                {panel.kind === "donut" && <Donut rows={panel.rows} format={panel.format} centerLabel={panel.metric} />}
                {panel.kind === "line" && <TrendChart rows={panel.rows} format={panel.format} />}
              </article>
            ))}
          </section>
        </>
      )}
    </ToolPage>
  );
}
