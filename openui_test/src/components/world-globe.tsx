"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Globe2, LocateFixed, Pause, Play } from "lucide-react";

import type { GlobePalette, GlobeView } from "@/components/globe/globe-canvas";
import { WorldMap } from "@/components/world-map";
import { formatValue, metricFormat, type GeoPlace, type GeoRegion } from "@/lib/geo";

/**
 * Interactive 3D globe (Three.js via react-globe.gl) for geographic answers:
 * an extruded choropleth of the marked countries, a glowing value column and
 * a pulsing ring per place, labels for the leaders, hover tooltips, a gentle
 * auto-rotation and a World / Focus camera toggle.
 *
 * Inline chat cards mount the WebGL scene only while on screen, so a long
 * conversation never runs out of WebGL contexts. Without WebGL the flat
 * <WorldMap> is shown instead.
 */

const GlobeCanvas = dynamic(() => import("@/components/globe/globe-canvas"), {
  ssr: false,
  loading: () => <div className="qc-globe__loading"><Globe2 size={16} /> Spinning up the globe…</div>,
});

let webglSupport: boolean | null = null;
function hasWebGL(): boolean {
  if (webglSupport === null) {
    try {
      const canvas = document.createElement("canvas");
      webglSupport = Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
    } catch {
      webglSupport = false;
    }
  }
  return webglSupport;
}

/** Aurora value ramp, low → high (tools.css defines the themed --qc-globe-ramp-N tokens). */
const RAMP_FALLBACK = ["#5b6cff", "#22c7f0", "#2fd6a0", "#ffc247", "#ff7f5c", "#ff4fa3"];

function readPalette(el: HTMLElement): GlobePalette {
  const style = getComputedStyle(el);
  const theme = el.closest("[data-theme]")?.getAttribute("data-theme");
  const get = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    accent: get("--qc-accent", "#ff7f5c"),
    accent2: get("--qc-accent-2", "#ff5d8f"),
    ocean: get("--qc-globe-ocean", "#0e1324"),
    land: get("--qc-globe-land", "#2a3047"),
    dot: get("--qc-globe-dot", "rgba(150, 168, 220, 0.5)"),
    border: get("--qc-globe-border", "rgba(255,255,255,0.18)"),
    ink: get("--qc-ink", "#f1f2f8"),
    atmosphere: get("--qc-globe-atmosphere", "#ff9878"),
    ramp: RAMP_FALLBACK.map((fallback, i) => get(`--qc-globe-ramp-${i + 1}`, fallback)),
    dark: theme !== "light",
  };
}

/** Palette from the CSS tokens, refreshed when the app theme flips. */
function usePalette(ref: React.RefObject<HTMLElement | null>) {
  const [palette, setPalette] = useState<GlobePalette | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setPalette(readPalette(el));
    update();
    const themed = el.closest("[data-theme]") ?? document.documentElement;
    const observer = new MutationObserver(update);
    observer.observe(themed, { attributes: true, attributeFilter: ["data-theme", "class"] });
    return () => observer.disconnect();
  }, [ref]);
  return palette;
}

function useSize(ref: React.RefObject<HTMLElement | null>) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

function useInView(ref: React.RefObject<HTMLElement | null>, enabled: boolean) {
  const [inView, setInView] = useState(!enabled);
  useEffect(() => {
    const el = ref.current;
    if (!enabled || !el) return;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { rootMargin: "240px 0px" });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, enabled]);
  return inView;
}

/**
 * Legend gradient that follows the globe's colour curve: places take the
 * aurora ramp colour at √(value / max), so the bar (linear in value) runs
 * through the cool hues quickly, exactly like the countries do.
 */
const legendRamp = (() => {
  const last = RAMP_FALLBACK.length - 1;
  const stops = [0, 0.02, 0.06, 0.12, 0.2, 0.3, 0.42, 0.56, 0.72, 0.86, 1].map((f) => {
    const x = Math.sqrt(f) * last;
    const i = Math.min(last - 1, Math.floor(x));
    const pct = Math.round((x - i) * 100);
    return `color-mix(in srgb, var(--qc-globe-ramp-${i + 2}) ${pct}%, var(--qc-globe-ramp-${i + 1})) ${Math.round(f * 100)}%`;
  });
  return `linear-gradient(90deg, ${stops.join(", ")})`;
})();

const noSubscribe = () => () => {};
const prefersReducedMotion = () => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

export type WorldGlobeProps = {
  places: GeoPlace[];
  regions?: GeoRegion[];
  metric?: string | null;
  /** Compact = inline chat card: shorter canvas, no zoom, fewer labels. */
  compact?: boolean;
  initialView?: GlobeView;
  /** Highlight a place (e.g. hovered row in a ranking list). */
  highlightKey?: string | null;
  onHoverPlace?: (key: string | null) => void;
  ariaLabel?: string;
};

export function WorldGlobe({
  places,
  regions = [],
  metric,
  compact = false,
  initialView = "focus",
  highlightKey,
  onHoverPlace,
  ariaLabel,
}: WorldGlobeProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const width = useSize(wrapRef);
  const palette = usePalette(wrapRef);
  const inView = useInView(wrapRef, compact);
  // null on the server: the scene only ever mounts in the browser.
  const webgl = useSyncExternalStore<boolean | null>(noSubscribe, hasWebGL, () => null);
  const reducedMotion = useSyncExternalStore(noSubscribe, prefersReducedMotion, () => false);
  const [view, setView] = useState<GlobeView>(initialView);
  const [rotatePref, setRotating] = useState<boolean | null>(null);
  const rotating = rotatePref ?? !reducedMotion;
  const stopRotating = useCallback(() => setRotating(false), []);

  const format = metricFormat(metric);
  const max = places.reduce((m, p) => Math.max(m, typeof p.value === "number" ? p.value : 0), 0);
  const height = compact ? 320 : Math.max(380, Math.min(560, Math.round(width * 0.62)));
  const ranked = [...places].sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
  const summary =
    ariaLabel ??
    `Interactive globe marking ${places.length} place${places.length === 1 ? "" : "s"}${
      regions.length ? ` in ${regions.map((r) => r.name).join(", ")}` : ""
    }: ${ranked
      .slice(0, 8)
      .map((p) => (typeof p.value === "number" ? `${p.name} ${formatValue(p.value, format)}` : p.name))
      .join(", ")}`;

  if (webgl === false) {
    return (
      <WorldMap
        places={places}
        metric={metric}
        compact={compact}
        initialView={initialView}
        highlightKey={highlightKey}
        onHoverPlace={onHoverPlace}
        ariaLabel={ariaLabel}
      />
    );
  }

  return (
    <div
      className={`qc-globe ${compact ? "qc-globe--compact" : ""}`}
      ref={wrapRef}
      style={{ height }}
      role="img"
      aria-label={summary}
    >
      {webgl && palette && width > 0 && inView && (
        <GlobeCanvas
          width={width}
          height={height}
          places={places}
          regions={regions}
          metric={metric}
          format={format}
          palette={palette}
          view={view}
          compact={compact}
          highlightKey={highlightKey}
          onHoverPlace={onHoverPlace}
          onUserInteract={stopRotating}
          autoRotate={rotating}
          reducedMotion={reducedMotion}
        />
      )}

      <div className="qc-globe__controls">
        <button
          type="button"
          className={view === "world" ? "is-active" : ""}
          onClick={() => setView("world")}
          aria-pressed={view === "world"}
          title="Zoom out to the whole globe"
        >
          <Globe2 size={13} /> World
        </button>
        <button
          type="button"
          className={view === "focus" ? "is-active" : ""}
          onClick={() => setView("focus")}
          aria-pressed={view === "focus"}
          title="Fly to the marked places"
        >
          <LocateFixed size={13} /> Focus
        </button>
        <button
          type="button"
          onClick={() => setRotating(!rotating)}
          aria-pressed={rotating}
          title={rotating ? "Pause rotation" : "Rotate the globe"}
          aria-label={rotating ? "Pause rotation" : "Rotate the globe"}
        >
          {rotating ? <Pause size={13} /> : <Play size={13} />}
        </button>
      </div>

      {max > 0 && (
        <div className="qc-globe__legend" aria-hidden="true">
          <span className="qc-globe__legend-label">{metric ?? "Value"}</span>
          <span className="qc-globe__legend-bar" style={{ background: legendRamp }} />
          <span className="qc-globe__legend-scale">
            <span>{formatValue(0, format)}</span>
            <span>{formatValue(max / 2, format)}</span>
            <span>{formatValue(max, format)}</span>
          </span>
        </div>
      )}
      {!compact && <span className="qc-globe__hint" aria-hidden="true">Drag to spin · scroll to zoom · hover for details</span>}
    </div>
  );
}
