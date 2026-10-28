/** Shapes of the backend's geo_map / data_insights tool results (backend/geo.py, backend/insights.py). */

export type GeoPlace = {
  key: string;
  kind: "country" | "city";
  /** ISO 3166-1 numeric code of the country (the world-atlas feature id). */
  id: string;
  name: string;
  country?: string;
  continent: string;
  lat: number;
  lon: number;
  value?: number | null;
  share?: number | null;
};

export type GeoInsight = { tone: string; title: string; detail: string };

/** A continent or business region named in the question (e.g. Europe, APAC). */
export type GeoRegion = {
  name: string;
  /** ISO 3166-1 numeric codes of its countries. */
  ids: string[];
  lat: number;
  lon: number;
};

export type GeoPayload = {
  source?: "database" | "question" | "answer" | null;
  metric?: string | null;
  total?: number | null;
  places: GeoPlace[];
  regions?: GeoRegion[];
  continents: string[];
  insights: GeoInsight[];
};

export type InsightCard = { kind: string; title: string; value: string; detail: string; source?: string };

export type InsightsPayload = {
  metric: string;
  shape: "time" | "category";
  groups: number;
  total: number;
  series: { label: string; value: number }[];
  insights: InsightCard[];
};

export type ValueFormat = "number" | "currency" | "percent";

export function formatValue(value: number | null | undefined, format: ValueFormat = "number", compact = true): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (format === "percent") return `${(value * 100).toFixed(value < 0.1 ? 1 : 0)}%`;
  const options: Intl.NumberFormatOptions = compact && Math.abs(value) >= 10_000
    ? { notation: "compact", maximumFractionDigits: 1 }
    : { maximumFractionDigits: Number.isInteger(value) ? 0 : 2 };
  if (format === "currency") return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", ...options }).format(value);
  return new Intl.NumberFormat("en-US", options).format(value);
}

/** Currency when the metric label says so (e.g. "Annual hr tech spend (USD)", "Revenue"). */
export function metricFormat(metric?: string | null): ValueFormat {
  return metric && /usd|revenue|spend|price|amount|\$/i.test(metric) ? "currency" : "number";
}

export function parseJSON<T>(value: unknown): T | null {
  if (value == null) return null;
  if (typeof value === "object") return value as T;
  try {
    return JSON.parse(String(value)) as T;
  } catch {
    return null;
  }
}
