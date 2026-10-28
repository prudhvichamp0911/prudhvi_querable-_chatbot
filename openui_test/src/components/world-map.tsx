"use client";

import { useId, useMemo, useRef, useState } from "react";
import { geoCircle, geoGraticule10, geoNaturalEarth1, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import { Globe2, LocateFixed } from "lucide-react";
import countriesTopology from "world-atlas/countries-110m.json";

import { formatValue, metricFormat, type GeoPlace } from "@/lib/geo";

/**
 * Professional world map for geographic answers: a Natural Earth projection,
 * a single-hue choropleth (darker = more), sized markers with a pulsing halo
 * for every place in the answer, top-place labels, a hover tooltip and a
 * World / Focus toggle that zooms to the marked region.
 *
 * Colors come from the --qc-map-* and --qc-accent tokens, so light and dark
 * themes each get their own steps.
 */

type CountryFeature = Feature<Geometry, { name: string }>;

const WIDTH = 960;
const HEIGHT = 500;

let cachedCountries: CountryFeature[] | null = null;

function countries(): CountryFeature[] {
  if (!cachedCountries) {
    const topology = countriesTopology as unknown as Topology<{ countries: GeometryCollection<{ name: string }> }>;
    const collection = feature(topology, topology.objects.countries) as FeatureCollection<Geometry, { name: string }>;
    // Antarctica takes a fifth of the canvas and never carries business data.
    cachedCountries = collection.features.filter((item) => item.properties?.name !== "Antarctica");
  }
  return cachedCountries;
}

type Hover = { x: number; y: number; width: number; place: GeoPlace } | null;

export type WorldMapProps = {
  places: GeoPlace[];
  metric?: string | null;
  /** Compact = inline chat card: fewer labels, shorter canvas. */
  compact?: boolean;
  /** Initial view. Defaults to focus when the places sit in one region. */
  initialView?: "world" | "focus";
  /** Highlight a place (e.g. hovered row in a ranking list). */
  highlightKey?: string | null;
  onHoverPlace?: (key: string | null) => void;
  ariaLabel?: string;
};

export function WorldMap({
  places,
  metric,
  compact = false,
  initialView,
  highlightKey,
  onHoverPlace,
  ariaLabel,
}: WorldMapProps) {
  const clipId = useId().replace(/:/g, "");
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Hover>(null);

  const features = countries();
  const valued = places.filter((p) => typeof p.value === "number");
  const max = valued.reduce((m, p) => Math.max(m, p.value ?? 0), 0);
  const format = metricFormat(metric);

  const spread = useMemo(() => {
    if (places.length === 0) return 0;
    const lons = places.map((p) => p.lon);
    const lats = places.map((p) => p.lat);
    return Math.max(Math.max(...lons) - Math.min(...lons), (Math.max(...lats) - Math.min(...lats)) * 1.6);
  }, [places]);
  const [view, setView] = useState<"world" | "focus">(initialView ?? (spread < 110 ? "focus" : "world"));

  const byCountry = useMemo(() => {
    const map = new Map<string, GeoPlace>();
    for (const place of places) {
      if (place.kind !== "country") continue;
      map.set(place.id, place);
    }
    // A city-only answer still tints the country it sits in.
    for (const place of places) {
      if (place.kind === "city" && !map.has(place.id)) map.set(place.id, { ...place, value: null });
    }
    return map;
  }, [places]);

  const { path, project } = useMemo(() => {
    const projection = geoNaturalEarth1();
    const pad = compact ? 18 : 28;
    if (view === "focus" && places.length > 0) {
      // Fit to the marked countries plus a context circle around each place.
      const focus: Feature[] = [
        ...features.filter((f) => byCountry.has(String(f.id)) && byCountry.get(String(f.id))?.kind === "country")
          .filter((f) => !["840", "643", "250"].includes(String(f.id)) || places.length > 1),
        ...places.map((p) => ({
          type: "Feature" as const,
          properties: {},
          geometry: geoCircle().center([p.lon, p.lat]).radius(places.length === 1 ? 14 : 7)(),
        })),
      ];
      projection.fitExtent([[pad, pad], [WIDTH - pad, HEIGHT - pad]], { type: "FeatureCollection", features: focus });
    } else {
      projection.fitExtent([[pad, pad], [WIDTH - pad, HEIGHT - pad]], { type: "Sphere" });
    }
    return { path: geoPath(projection), project: (lon: number, lat: number) => projection([lon, lat]) };
  }, [view, places, features, byCountry, compact]);

  const fillFor = (place: GeoPlace | undefined) => {
    if (!place) return "var(--qc-map-land)";
    if (typeof place.value !== "number" || max <= 0) return "color-mix(in oklab, var(--qc-accent) 55%, var(--qc-map-land))";
    const t = Math.sqrt(place.value / max);
    return `color-mix(in oklab, var(--qc-accent) ${Math.round(22 + t * 78)}%, var(--qc-map-land))`;
  };

  const radiusFor = (place: GeoPlace) => {
    if (typeof place.value !== "number" || max <= 0) return compact ? 5 : 6;
    return (compact ? 4 : 5) + Math.sqrt(place.value / max) * (compact ? 9 : 13);
  };

  const ranked = [...places].sort((a, b) => (b.value ?? 0) - (a.value ?? 0));

  // Greedy label placement in rank order: right of the marker, else left,
  // else skip — so neighbours like the UK and Germany never overprint.
  const labels = (() => {
    const placed: { x: number; y: number; w: number; h: number }[] = [];
    const out: { place: GeoPlace; x: number; y: number; anchor: "start" | "end"; showValue: boolean }[] = [];
    const fontSize = compact ? 18 : 13;
    for (const place of ranked.slice(0, compact ? 4 : 8)) {
      const point = project(place.lon, place.lat);
      if (!point) continue;
      const r = radiusFor(place);
      const showValue = typeof place.value === "number" && !compact;
      const text = place.name + (showValue ? ` ${formatValue(place.value, format)}` : "");
      const w = text.length * fontSize * 0.58;
      const h = fontSize + 4;
      const candidates: ("start" | "end")[] = point[0] < WIDTH - w - r - 12 ? ["start", "end"] : ["end", "start"];
      for (const anchor of candidates) {
        const x = anchor === "start" ? point[0] + r + 6 : point[0] - r - 6;
        const box = { x: anchor === "start" ? x : x - w, y: point[1] - h / 2, w, h };
        if (box.x < 4 || box.x + box.w > WIDTH - 4) continue;
        const hit = placed.some((b) => box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y);
        if (!hit) {
          placed.push(box);
          out.push({ place, x, y: point[1] + 4, anchor, showValue });
          break;
        }
      }
    }
    return out;
  })();

  const showHover = (event: React.PointerEvent, place: GeoPlace) => {
    const box = wrapRef.current?.getBoundingClientRect();
    if (!box) return;
    setHover({ x: event.clientX - box.left, y: event.clientY - box.top, width: box.width, place });
    onHoverPlace?.(place.key);
  };
  const clearHover = () => {
    setHover(null);
    onHoverPlace?.(null);
  };

  const summary =
    ariaLabel ??
    `World map marking ${places.length} place${places.length === 1 ? "" : "s"}: ${ranked
      .slice(0, 8)
      .map((p) => (typeof p.value === "number" ? `${p.name} ${formatValue(p.value, format)}` : p.name))
      .join(", ")}`;

  return (
    <div className={`qc-map ${compact ? "qc-map--compact" : ""}`} ref={wrapRef}>
      <svg
        className="qc-map__svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={summary}
        onPointerLeave={clearHover}
      >
        <defs>
          <clipPath id={`sphere-${clipId}`}>
            <path d={path({ type: "Sphere" }) ?? ""} />
          </clipPath>
          <radialGradient id={`glow-${clipId}`}>
            <stop offset="0%" stopColor="var(--qc-accent)" stopOpacity="0.45" />
            <stop offset="100%" stopColor="var(--qc-accent)" stopOpacity="0" />
          </radialGradient>
        </defs>
        <path className="qc-map__sphere" d={path({ type: "Sphere" }) ?? ""} />
        <g clipPath={`url(#sphere-${clipId})`}>
          <path className="qc-map__graticule" d={path(geoGraticule10()) ?? ""} />
          {features.map((country) => {
            const place = byCountry.get(String(country.id));
            const active = place && (highlightKey === place.key || hover?.place.id === place.id);
            return (
              <path
                key={String(country.id ?? country.properties.name)}
                d={path(country) ?? ""}
                className={`qc-map__country ${place ? "qc-map__country--marked" : ""} ${active ? "qc-map__country--active" : ""}`}
                style={{ fill: fillFor(place) }}
                onPointerMove={place ? (event) => showHover(event, place) : undefined}
                onPointerLeave={place ? clearHover : undefined}
              />
            );
          })}
        </g>

        {ranked.map((place, index) => {
          const point = project(place.lon, place.lat);
          if (!point) return null;
          const [x, y] = point;
          const r = radiusFor(place);
          const active = highlightKey === place.key || hover?.place.key === place.key;
          return (
            <g
              key={place.key}
              className={`qc-map__marker ${active ? "qc-map__marker--active" : ""}`}
              transform={`translate(${x.toFixed(1)} ${y.toFixed(1)})`}
              style={{ animationDelay: `${index * 70}ms` }}
              onPointerMove={(event) => showHover(event, place)}
              onPointerLeave={clearHover}
            >
              <circle className="qc-map__halo" r={r * 2.4} fill={`url(#glow-${clipId})`} />
              <circle className="qc-map__pulse" r={r} />
              <circle className="qc-map__dot" r={r} />
              {place.kind === "city" && <circle className="qc-map__city-core" r={Math.max(2, r / 3)} />}
              <circle className="qc-map__hit" r={r + 8} />
            </g>
          );
        })}

        {labels.map(({ place, x, y, anchor, showValue }) => (
          <text key={`label-${place.key}`} className="qc-map__label" x={x} y={y} textAnchor={anchor}>
            {place.name}
            {showValue && <tspan className="qc-map__label-value"> {formatValue(place.value, format)}</tspan>}
          </text>
        ))}
      </svg>

      <div className="qc-map__controls">
        <button
          type="button"
          className={view === "world" ? "is-active" : ""}
          onClick={() => setView("world")}
          aria-pressed={view === "world"}
          title="Show the whole world"
        >
          <Globe2 size={13} /> World
        </button>
        <button
          type="button"
          className={view === "focus" ? "is-active" : ""}
          onClick={() => setView("focus")}
          aria-pressed={view === "focus"}
          title="Zoom to the marked places"
        >
          <LocateFixed size={13} /> Focus
        </button>
      </div>

      {max > 0 && (
        <div className="qc-map__legend" aria-hidden="true">
          <span className="qc-map__legend-label">{metric ?? "Value"}</span>
          <span className="qc-map__legend-bar" />
          <span className="qc-map__legend-scale">
            <span>{formatValue(0, format)}</span>
            <span>{formatValue(max, format)}</span>
          </span>
        </div>
      )}

      {hover && (
        <div
          className="qc-map__tooltip"
          style={{
            left: Math.max(8, Math.min(hover.x + 14, hover.width - 200)),
            top: Math.max(hover.y - 12, 8),
          }}
          role="status"
        >
          <strong>{hover.place.name}</strong>
          <span className="qc-map__tooltip-sub">
            {hover.place.kind === "city" ? `${hover.place.country} · ` : ""}
            {hover.place.continent}
          </span>
          {typeof hover.place.value === "number" && (
            <span className="qc-map__tooltip-value">
              {formatValue(hover.place.value, format, false)}
              <em>{metric}</em>
            </span>
          )}
          {typeof hover.place.share === "number" && (
            <span className="qc-map__tooltip-share">{(hover.place.share * 100).toFixed(1)}% of total</span>
          )}
        </div>
      )}
    </div>
  );
}
