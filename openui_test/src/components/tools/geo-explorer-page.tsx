"use client";

import { useState } from "react";
import { Globe2 } from "lucide-react";

import { GeoPanel } from "@/components/geo-panel";
import { AskButton, LoadState, ToolPage, useApi } from "@/components/tools/shared";
import type { GeoPayload } from "@/lib/geo";

type Dataset = { collection: string; place_field: string; numeric_fields: string[] };

const pretty = (text: string) => text.replace(/_/g, " ").replace(/\busd\b/i, "(USD)");

export function GeoExplorerPage() {
  const datasets = useApi<{ datasets: Dataset[] }>("/api/geo/datasets");
  const [collection, setCollection] = useState<string | null>(null);
  const [measure, setMeasure] = useState("count");

  const list = datasets.data?.datasets ?? [];
  const dataset = list.find((d) => d.collection === collection) ?? list.find((d) => d.collection === "span_companies") ?? list[0];
  const [op, field] = measure === "count" ? ["count", ""] : measure.split(":");
  const validField = !field || dataset?.numeric_fields.includes(field);

  const query = dataset
    ? `/api/geo/explore?${new URLSearchParams({
        collection: dataset.collection,
        place_field: dataset.place_field,
        op: validField ? op : "count",
        ...(field && validField ? { value_field: field } : {}),
      })}`
    : null;
  const geo = useApi<GeoPayload>(query);

  const measureLabel = measure === "count" || !validField ? "records" : `${op === "avg" ? "average" : "total"} ${pretty(field)}`;

  return (
    <ToolPage
      icon={<Globe2 size={13} />}
      eyebrow="Geo explorer"
      title="Where it happens"
      description="Map any collection that has a country or city field. Pick a dataset and a measure; every number comes from a read-only MongoDB aggregation."
      actions={
        dataset && (
          <AskButton prompt={`Show ${measureLabel} of ${pretty(dataset.collection)} by ${dataset.place_field}`} />
        )
      }
    >
      <LoadState loading={datasets.loading} error={datasets.error} onRetry={datasets.reload} />
      {list.length === 0 && !datasets.loading && !datasets.error && (
        <div className="qc-state">No collection with a country or city field was found.</div>
      )}
      {dataset && (
        <>
          <div className="qc-filter-row">
            <label className="qc-field">
              <span>Dataset</span>
              <select
                value={dataset.collection}
                onChange={(event) => {
                  setCollection(event.target.value);
                  setMeasure("count");
                }}
              >
                {list.map((d) => (
                  <option key={d.collection} value={d.collection}>
                    {pretty(d.collection)} · by {d.place_field}
                  </option>
                ))}
              </select>
            </label>
            <label className="qc-field">
              <span>Measure</span>
              <select value={validField ? measure : "count"} onChange={(event) => setMeasure(event.target.value)}>
                <option value="count">Number of records</option>
                {dataset.numeric_fields.flatMap((f) => [
                  <option key={`sum:${f}`} value={`sum:${f}`}>
                    Total {pretty(f)}
                  </option>,
                  <option key={`avg:${f}`} value={`avg:${f}`}>
                    Average {pretty(f)}
                  </option>,
                ])}
              </select>
            </label>
          </div>
          <LoadState loading={geo.loading && !geo.data} error={geo.error} onRetry={geo.reload} />
          {geo.data && geo.data.places.length > 0 && (
            <GeoPanel
              key={query ?? ""}
              data={{ ...geo.data, metric: measureLabel[0].toUpperCase() + measureLabel.slice(1) }}
              title={`${pretty(dataset.collection)} — ${measureLabel} by ${dataset.place_field}`}
            />
          )}
        </>
      )}
    </ToolPage>
  );
}
