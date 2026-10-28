"use client";

import { defineArtifactRenderer } from "@openuidev/react-ui";
import {
  ArrowDownRight,
  ArrowUpRight,
  Crown,
  Gauge,
  Globe2,
  Layers,
  Lightbulb,
  Maximize2,
  Mountain,
  Scale,
  Sigma,
  TrendingUp,
} from "lucide-react";

import { BarList, Sparkline, TrendChart } from "@/components/charts";
import { GeoInsightList, GeoPanel } from "@/components/geo-panel";
import { WorldGlobe } from "@/components/world-globe";
import { formatValue, metricFormat, parseJSON, type GeoPayload, type InsightsPayload } from "@/lib/geo";

/**
 * Renderers for the backend's analysis tool calls (backend/chat_service.py
 * analysis_events): `geo_map` draws every place in the answer on a world map,
 * `data_insights` shows the deterministic insight cards. Both are inline
 * cards in the chat with a full view in the side panel.
 */

type GeoProps = { data: GeoPayload | null; question: string };

const SOURCE_LABEL: Record<string, string> = {
  database: "from the query result",
  question: "named in your question",
  answer: "mentioned in the answer",
};

export const geoMapRenderer = defineArtifactRenderer<GeoProps>({
  type: "qc_geo_map",
  toolName: "geo_map",
  parser: ({ args, response }) => {
    const data = parseJSON<GeoPayload>(response);
    const question = parseJSON<{ question?: string }>(args)?.question ?? "";
    if (data && !data.places?.length && !data.regions?.length) return null;
    const regionNames = (data?.regions ?? []).map((r) => r.name);
    const id = `geo-${(data?.places ?? []).map((p) => p.key).join("|")}-${regionNames.join("|")}-${question.length}`;
    return {
      props: { data, question },
      meta: data
        ? {
            id,
            version: 1,
            heading: `Globe · ${
              data.places.length
                ? [...data.places]
                    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
                    .slice(0, 3)
                    .map((p) => p.name)
                    .join(", ")
                : regionNames.join(", ")
            }`,
          }
        : null,
    };
  },
  preview: ({ data }, controls) => {
    if (!data) {
      return (
        <div className="qc-geo-card qc-geo-card--loading">
          <Globe2 size={16} /> Locating places…
        </div>
      );
    }
    const format = metricFormat(data.metric);
    const top = [...data.places].sort((a, b) => (b.value ?? 0) - (a.value ?? 0)).slice(0, 4);
    return (
      <section className="qc-geo-card" aria-label="Geographic view">
        <header className="qc-geo-card__head">
          <span className="qc-geo-card__badge">
            <Globe2 size={14} />
          </span>
          <div className="qc-geo-card__title">
            <strong>
              {data.places.length === 0
                ? (data.regions ?? []).map((r) => r.name).join(" · ")
                : data.places.length === 1
                  ? data.places[0].name
                  : `${data.places.length} places on the globe`}
            </strong>
            <span className="qc-muted">
              {data.continents.join(" · ")} — {SOURCE_LABEL[data.source ?? ""] ?? "geographic view"}
            </span>
          </div>
          <button type="button" className="qc-ghost-button" onClick={controls.open}>
            <Maximize2 size={13} /> Full analysis
          </button>
        </header>
        <WorldGlobe places={data.places} regions={data.regions} metric={data.metric} compact />
        <div className="qc-geo-card__chips">
          {top.map((place) => (
            <span key={place.key} className="qc-place-chip">
              <span className="qc-place-chip__dot" />
              {place.name}
              {typeof place.value === "number" && <b>{formatValue(place.value, format)}</b>}
            </span>
          ))}
          {data.places.length > top.length && <span className="qc-muted">+{data.places.length - top.length} more</span>}
        </div>
        <GeoInsightList insights={data.insights.slice(0, 2)} />
      </section>
    );
  },
  actual: ({ data }) => (data ? <GeoPanel data={data} /> : null),
  label: "Globe",
  icon: <Globe2 size={16} />,
});

const INSIGHT_ICONS: Record<string, React.ReactNode> = {
  leader: <Crown size={15} />,
  spread: <Scale size={15} />,
  concentration: <Layers size={15} />,
  skew: <Gauge size={15} />,
  average: <Sigma size={15} />,
  trend: <TrendingUp size={15} />,
  peak: <Mountain size={15} />,
  jump: <ArrowUpRight size={15} />,
  drop: <ArrowDownRight size={15} />,
};

type InsightProps = { data: InsightsPayload | null };

export function InsightCards({ data }: { data: InsightsPayload }) {
  return (
    <div className="qc-insight-grid">
      {data.insights.map((card, index) => (
        <article key={card.title} className={`qc-insight qc-insight--${card.kind}`} style={{ animationDelay: `${index * 60}ms` }}>
          <span className="qc-insight__icon">{INSIGHT_ICONS[card.kind] ?? <Lightbulb size={15} />}</span>
          <span className="qc-insight__value">{card.value}</span>
          <span className="qc-insight__title">{card.title}</span>
          <span className="qc-insight__detail">{card.detail}</span>
          {index === 0 && data.shape === "time" && <Sparkline values={data.series.map((s) => s.value)} />}
        </article>
      ))}
    </div>
  );
}

export const dataInsightsRenderer = defineArtifactRenderer<InsightProps>({
  type: "qc_data_insights",
  toolName: "data_insights",
  parser: ({ response }) => {
    const data = parseJSON<InsightsPayload>(response);
    if (data && !data.insights?.length) return null;
    return { props: { data }, meta: null };
  },
  preview: ({ data }, controls) =>
    data ? (
      <section className="qc-insight-strip" aria-label="Key insights">
        <header>
          <Lightbulb size={14} /> <strong>Key insights</strong>
          <span className="qc-muted"> · {data.groups} {data.shape === "time" ? "periods" : "groups"} · {data.metric}</span>
          <button type="button" className="qc-ghost-button" onClick={controls.open}>
            <Maximize2 size={13} /> Explore
          </button>
        </header>
        <InsightCards data={data} />
      </section>
    ) : null,
  actual: ({ data }) =>
    data ? (
      <div className="qc-geo-panel">
        <header className="qc-geo-panel__head">
          <div>
            <p className="qc-eyebrow">
              <Lightbulb size={13} /> Data insights
            </p>
            <h2>{data.metric}</h2>
          </div>
        </header>
        <InsightCards data={data} />
        <section className="qc-tile">
          <h3 className="qc-tile__title">{data.shape === "time" ? "Over time" : "Ranking"}</h3>
          {data.shape === "time" ? (
            <TrendChart rows={data.series} format={metricFormat(data.metric)} />
          ) : (
            <BarList rows={data.series} format={metricFormat(data.metric)} max={24} />
          )}
        </section>
      </div>
    ) : null,
  label: "Insights",
  icon: <Lightbulb size={16} />,
});
