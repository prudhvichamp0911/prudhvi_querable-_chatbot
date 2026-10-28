"use client";

import { useState } from "react";
import { Crown, Globe2, Layers, MapPin, Scale, Sparkles } from "lucide-react";

import { BarList, Donut } from "@/components/charts";
import { WorldGlobe } from "@/components/world-globe";
import { formatValue, metricFormat, type GeoPayload } from "@/lib/geo";

const TONE_ICONS: Record<string, React.ReactNode> = {
  lead: <Crown size={15} />,
  gap: <Scale size={15} />,
  concentration: <Layers size={15} />,
  region: <Globe2 size={15} />,
  spread: <MapPin size={15} />,
};

export function GeoInsightList({ insights }: { insights: GeoPayload["insights"] }) {
  if (!insights.length) return null;
  return (
    <ul className="qc-geo-insights">
      {insights.map((item) => (
        <li key={item.title} className={`qc-geo-insight qc-geo-insight--${item.tone}`}>
          <span className="qc-geo-insight__icon">{TONE_ICONS[item.tone] ?? <Sparkles size={15} />}</span>
          <span>
            <strong>{item.title}</strong>
            <span className="qc-muted"> {item.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Full geographic analysis: big map, ranking, continent mix, insights, table. */
export function GeoPanel({ data, title }: { data: GeoPayload; title?: string }) {
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const format = metricFormat(data.metric);
  const valued = data.places.filter((p) => typeof p.value === "number");
  const nameToKey = new Map(data.places.map((p) => [p.name, p.key]));
  const keyToName = new Map(data.places.map((p) => [p.key, p.name]));

  const continents = Object.entries(
    valued.reduce<Record<string, number>>((acc, p) => {
      acc[p.continent] = (acc[p.continent] ?? 0) + (p.value ?? 0);
      return acc;
    }, {}),
  )
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value);

  return (
    <div className="qc-geo-panel">
      <header className="qc-geo-panel__head">
        <div>
          <p className="qc-eyebrow">
            <Globe2 size={13} /> Geographic analysis
          </p>
          <h2>
            {title ??
              (data.metric
                ? `${data.metric} by location`
                : data.places.length === 0 && data.regions?.length
                  ? data.regions.map((r) => r.name).join(" · ")
                  : "Places in this answer")}
          </h2>
        </div>
        <dl className="qc-geo-panel__facts">
          <div>
            <dt>Places</dt>
            <dd>{data.places.length}</dd>
          </div>
          <div>
            <dt>Continents</dt>
            <dd>{data.continents.length}</dd>
          </div>
          {data.total != null && (
            <div>
              <dt>Total</dt>
              <dd>{formatValue(data.total, format)}</dd>
            </div>
          )}
        </dl>
      </header>

      <WorldGlobe
        places={data.places}
        regions={data.regions}
        metric={data.metric}
        highlightKey={hoverKey}
        onHoverPlace={setHoverKey}
      />

      <GeoInsightList insights={data.insights} />

      <div className="qc-geo-panel__grid">
        {valued.length > 0 && (
          <section className="qc-tile">
            <h3 className="qc-tile__title">Ranking</h3>
            <BarList
              rows={valued.map((p) => ({ label: p.name, value: p.value ?? 0 }))}
              format={format}
              highlight={hoverKey ? keyToName.get(hoverKey) : null}
              onHover={(label) => setHoverKey(label ? nameToKey.get(label) ?? null : null)}
            />
          </section>
        )}
        {continents.length > 1 && (
          <section className="qc-tile">
            <h3 className="qc-tile__title">By continent</h3>
            <Donut rows={continents} format={format} centerLabel={data.metric ?? "Total"} />
          </section>
        )}
      </div>

      <details className="qc-geo-panel__table">
        <summary>Table view</summary>
        <table className="qi-table">
          <thead>
            <tr>
              <th scope="col">Place</th>
              <th scope="col">Type</th>
              <th scope="col">Continent</th>
              {valued.length > 0 && <th scope="col">{data.metric ?? "Value"}</th>}
              {valued.length > 0 && <th scope="col">Share</th>}
            </tr>
          </thead>
          <tbody>
            {data.places.map((p) => (
              <tr key={p.key}>
                <td>{p.kind === "city" ? `${p.name}, ${p.country}` : p.name}</td>
                <td>{p.kind}</td>
                <td>{p.continent}</td>
                {valued.length > 0 && <td>{formatValue(p.value, format, false)}</td>}
                {valued.length > 0 && <td>{typeof p.share === "number" ? `${(p.share * 100).toFixed(1)}%` : "—"}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
