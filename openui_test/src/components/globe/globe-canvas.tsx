"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Globe, { type GlobeMethods } from "react-globe.gl";
import {
  AdditiveBlending,
  AmbientLight,
  BufferGeometry,
  CanvasTexture,
  Color,
  DirectionalLight,
  Float32BufferAttribute,
  MeshPhongMaterial,
  NormalBlending,
  Points,
  PointsMaterial,
  Sprite,
  SpriteMaterial,
} from "three";
import { geoCentroid } from "d3-geo";
import { feature } from "topojson-client";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import countriesTopology from "world-atlas/countries-110m.json";

import { formatValue, type GeoPlace, type GeoRegion, type ValueFormat } from "@/lib/geo";

/**
 * The Three.js scene behind <WorldGlobe>. Loaded with next/dynamic (no SSR)
 * because react-globe.gl touches `window` on import.
 *
 * Layers, bottom to top:
 *   halo      – a soft glow behind the globe whose hue drifts through the
 *               aurora spectrum and breathes slowly
 *   globe     – ocean sphere with an animated, colour-shifting fresnel rim
 *               and a faint moving shimmer
 *   hex dots  – halftone land, tinted by longitude across the spectrum, for
 *               every country the answer doesn't mention
 *   polygons  – marked countries, extruded and coloured by value along the
 *               multi-hue aurora ramp (3D choropleth); region countries get a wash
 *   arcs      – animated light trails from the leader to the other top places
 *   points    – a slim column per place, height = value, coloured by value
 *   rings     – ripples under the leaders in each place's own colour
 *   html      – ranked labels for the leaders (hidden behind the globe)
 *   stars     – coloured, twinkling starfield that drifts slowly (dark only)
 */

export type GlobePalette = {
  accent: string;
  accent2: string;
  ocean: string;
  land: string;
  dot: string;
  border: string;
  ink: string;
  atmosphere: string;
  /** Low → high colour ramp for values (aurora spectrum). */
  ramp: string[];
  dark: boolean;
};

export type GlobeView = "world" | "focus";

type CountryFeature = Feature<Geometry, { name: string }> & { id?: string | number };

let cachedCountries: CountryFeature[] | null = null;

/** A ring with fewer than 3 distinct points (world-atlas has one for North Korea). */
const degenerate = (ring: number[][]) => new Set(ring.map(([x, y]) => `${x},${y}`)).size < 3;

/** Drop degenerate parts: h3's polygonToCells throws on them, breaking the hex-dot layer. */
function cleanGeometry(geometry: Geometry): Geometry {
  if (geometry.type === "MultiPolygon") {
    return { ...geometry, coordinates: geometry.coordinates.filter((polygon) => !degenerate(polygon[0] ?? [])) };
  }
  return geometry;
}

function countries(): CountryFeature[] {
  if (!cachedCountries) {
    const topology = countriesTopology as unknown as Topology<{ countries: GeometryCollection<{ name: string }> }>;
    const collection = feature(topology, topology.objects.countries) as FeatureCollection<Geometry, { name: string }>;
    cachedCountries = collection.features
      .filter((item) => item.properties?.name !== "Antarctica")
      .map((item) => ({ ...item, geometry: cleanGeometry(item.geometry) })) as CountryFeature[];
  }
  return cachedCountries;
}

// ------------------------------------------------------------------ colour

function rgb(color: string): [number, number, number] {
  const hex = color.trim().replace("#", "");
  if (/^[0-9a-f]{6}$/i.test(hex)) {
    return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
  }
  const parts = color.match(/[\d.]+/g)?.map(Number) ?? [];
  return [parts[0] ?? 128, parts[1] ?? 128, parts[2] ?? 128];
}

function mix(a: string, b: string, t: number, alpha = 1): string {
  const [r1, g1, b1] = rgb(a);
  const [r2, g2, b2] = rgb(b);
  const c = (x: number, y: number) => Math.round(x + (y - x) * t);
  return `rgba(${c(r1, r2)}, ${c(g1, g2)}, ${c(b1, b2)}, ${alpha})`;
}

/** Colour at t ∈ [0, 1] along a multi-stop ramp. The legend in world-globe.tsx uses the same stops. */
export function rampAt(ramp: string[], t: number, alpha = 1): string {
  if (ramp.length === 0) return `rgba(128, 128, 128, ${alpha})`;
  if (ramp.length === 1) return mix(ramp[0], ramp[0], 0, alpha);
  const x = Math.min(1, Math.max(0, t)) * (ramp.length - 1);
  const i = Math.min(ramp.length - 2, Math.floor(x));
  return mix(ramp[i], ramp[i + 1], x - i, alpha);
}

/** three.js Color from any "#hex" / "rgb(a)(...)" string (alpha ignored). */
const toColor = (css: string) => {
  const [r, g, b] = rgb(css);
  return new Color(r / 255, g / 255, b / 255);
};

const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch] ?? ch);

// ------------------------------------------------------------------ camera

const toRad = (deg: number) => (deg * Math.PI) / 180;
const toDeg = (rad: number) => (rad * 180) / Math.PI;

function angularDistance(a: { lat: number; lon: number }, b: { lat: number; lon: number }) {
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return toDeg(2 * Math.asin(Math.min(1, Math.sqrt(h))));
}

/** Camera that frames every point: spherical centroid + altitude from the spread. */
export function focusFor(points: { lat: number; lon: number }[], compact: boolean) {
  if (points.length === 0) return { lat: 20, lng: 10, altitude: compact ? 2.4 : 2.2 };
  let x = 0;
  let y = 0;
  let z = 0;
  for (const p of points) {
    x += Math.cos(toRad(p.lat)) * Math.cos(toRad(p.lon));
    y += Math.cos(toRad(p.lat)) * Math.sin(toRad(p.lon));
    z += Math.sin(toRad(p.lat));
  }
  const center = { lat: toDeg(Math.atan2(z, Math.hypot(x, y))), lon: toDeg(Math.atan2(y, x)) };
  const spread = Math.max(...points.map((p) => angularDistance(center, p)));
  const altitude = Math.min(2.6, Math.max(compact ? 0.9 : 0.75, 0.55 + spread / 32)) + (compact ? 0.25 : 0);
  return { lat: center.lat, lng: center.lon, altitude };
}

// ------------------------------------------------------------------ stars

const STAR_TINTS = [
  [0.78, 0.84, 1.0],
  [1.0, 1.0, 1.0],
  [1.0, 0.86, 0.72],
  [0.72, 1.0, 0.94],
  [1.0, 0.76, 0.9],
];

/** Random points on a far shell around the globe (radius 100), each with a soft tint. */
function starShell(count: number, seed: number) {
  let s = seed;
  const rand = () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646;
  const positions: number[] = [];
  const colors: number[] = [];
  for (let i = 0; i < count; i++) {
    const u = rand() * 2 - 1;
    const theta = rand() * Math.PI * 2;
    const r = 900 + rand() * 600;
    const k = Math.sqrt(1 - u * u);
    positions.push(r * k * Math.cos(theta), r * u, r * k * Math.sin(theta));
    colors.push(...STAR_TINTS[Math.floor(rand() * STAR_TINTS.length)]);
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(positions, 3));
  geometry.setAttribute("color", new Float32BufferAttribute(colors, 3));
  return geometry;
}

/** White radial falloff used for the halo sprite; tinted per frame. */
function glowTexture() {
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.42, "rgba(255,255,255,0.55)");
    g.addColorStop(0.62, "rgba(255,255,255,0.18)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
  }
  return new CanvasTexture(canvas);
}

// ------------------------------------------------------------------ scene

/** Shader clock shared by every globe on the page (wall-clock seconds). */
const OCEAN_TIME = { value: 0 };
/** Halo sprite size around the radius-100 globe, and how far behind it it sits. */
const HALO_SIZE = 290;
const HALO_BACK = 150;

export type GlobeCanvasProps = {
  width: number;
  height: number;
  places: GeoPlace[];
  regions: GeoRegion[];
  metric?: string | null;
  format: ValueFormat;
  palette: GlobePalette;
  view: GlobeView;
  compact: boolean;
  highlightKey?: string | null;
  onHoverPlace?: (key: string | null) => void;
  onUserInteract?: () => void;
  autoRotate: boolean;
  reducedMotion: boolean;
};

type Arc = { startLat: number; startLng: number; endLat: number; endLng: number; colors: [string, string]; order: number };

export default function GlobeCanvas({
  width,
  height,
  places,
  regions,
  metric,
  format,
  palette,
  view,
  compact,
  highlightKey,
  onHoverPlace,
  onUserInteract,
  autoRotate,
  reducedMotion,
}: GlobeCanvasProps) {
  const globeRef = useRef<GlobeMethods | undefined>(undefined);
  const introPlayed = useRef(false);
  const [ready, setReady] = useState(false);
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const activeKey = highlightKey ?? hoverKey;
  const ramp = palette.ramp;

  const valued = places.filter((p) => typeof p.value === "number");
  const max = valued.reduce((m, p) => Math.max(m, p.value ?? 0), 0);
  const level = (place: GeoPlace | undefined) =>
    place && typeof place.value === "number" && max > 0 ? Math.sqrt(Math.max(0, place.value) / max) : null;
  /** A place's own colour: value along the ramp, or the ramp middle without a value. */
  const placeColor = (place: GeoPlace | undefined, alpha = 1) => rampAt(ramp, level(place) ?? 0.55, alpha);

  const byCountry = useMemo(() => {
    const map = new Map<string, GeoPlace>();
    for (const place of places) if (place.kind === "country") map.set(place.id, place);
    // A city-only answer still tints the country it sits in.
    for (const place of places) if (place.kind === "city" && !map.has(place.id)) map.set(place.id, { ...place, value: null });
    return map;
  }, [places]);

  const regionIds = useMemo(() => new Set(regions.flatMap((r) => r.ids)), [regions]);
  const ranked = useMemo(() => [...places].sort((a, b) => (b.value ?? 0) - (a.value ?? 0)), [places]);
  const rankOf = useMemo(() => new Map(ranked.map((p, i) => [p.key, i + 1])), [ranked]);

  // Marked countries are solid; everything else is halftone dots.
  const [solid, dotted] = useMemo(() => {
    const marked: CountryFeature[] = [];
    const rest: CountryFeature[] = [];
    for (const c of countries()) {
      const id = String(c.id);
      (byCountry.has(id) || regionIds.has(id) ? marked : rest).push(c);
    }
    return [marked, rest];
  }, [byCountry, regionIds]);

  // Halftone land tinted by longitude, so the idle globe reads as a soft rainbow.
  const dotColors = useMemo(() => {
    const colors = new Map<string, string>();
    const strength = palette.dark ? 0.5 : 0.42;
    for (const c of countries()) {
      const [lon] = geoCentroid(c);
      const t = ((lon + 180) / 360 + 1) % 1;
      colors.set(String(c.id), mix(palette.dot, rampAt(ramp, t), strength, palette.dark ? 0.62 : 0.55));
    }
    return colors;
  }, [palette.dot, palette.dark, ramp]);

  // ---- ocean: phong sphere + a fresnel rim whose colour drifts through the
  // ramp, plus a slow shimmer band. Uniforms live outside the shader so the
  // animation loop below can update them every frame.
  const oceanUniforms = useMemo(
    () => ({
      time: OCEAN_TIME,
      rimA: { value: new Color(palette.atmosphere) },
      rimB: { value: toColor(rampAt(ramp, 0.15)) },
      rimC: { value: toColor(rampAt(ramp, 0.85)) },
      rimStrength: { value: palette.dark ? 0.62 : 0.32 },
      shimmer: { value: palette.dark ? 0.06 : 0.035 },
    }),
    [palette.atmosphere, palette.dark, ramp],
  );

  const globeMaterial = useMemo(() => {
    const material = new MeshPhongMaterial({
      color: palette.ocean,
      emissive: palette.ocean,
      emissiveIntensity: palette.dark ? 0.55 : 0.25,
      specular: new Color(palette.dark ? "#3a4c88" : "#7f95c4"),
      shininess: 18,
    });
    material.onBeforeCompile = (shader) => {
      Object.assign(shader.uniforms, oceanUniforms);
      shader.fragmentShader = shader.fragmentShader
        .replace(
          "#include <common>",
          [
            "#include <common>",
            "uniform float time;",
            "uniform vec3 rimA;",
            "uniform vec3 rimB;",
            "uniform vec3 rimC;",
            "uniform float rimStrength;",
            "uniform float shimmer;",
          ].join("\n"),
        )
        .replace(
          "#include <dithering_fragment>",
          [
            "#include <dithering_fragment>",
            "vec3 n = normalize(vNormal);",
            "float rim = 1.0 - clamp(dot(n, normalize(vViewPosition)), 0.0, 1.0);",
            // The rim hue travels around the edge and through three colours.
            "float phase = atan(n.y, n.x) + time * 0.35;",
            "vec3 rimColor = mix(mix(rimA, rimB, 0.5 + 0.5 * sin(phase)), rimC, 0.5 + 0.5 * sin(phase * 0.5 - time * 0.21));",
            "gl_FragColor.rgb += rimColor * pow(rim, 2.6) * rimStrength;",
            // A faint diagonal shimmer drifting across the ocean.
            "float band = sin((n.x * 0.8 + n.y) * 7.0 - time * 0.9);",
            "gl_FragColor.rgb += mix(rimB, rimC, 0.5 + 0.5 * n.y) * smoothstep(0.75, 1.0, band) * shimmer * (1.0 - rim);",
          ].join("\n"),
        );
    };
    return material;
  }, [palette.ocean, palette.dark, oceanUniforms]);
  useEffect(() => () => globeMaterial.dispose(), [globeMaterial]);

  // ---- lights: soft ambient + a key light that rides with the camera, so
  // whichever side the user spins to is lit from the upper left.
  useEffect(() => {
    const globe = globeRef.current;
    if (!globe || !ready) return;
    const camera = globe.camera();
    const scene = globe.scene();
    const key = new DirectionalLight(0xffffff, palette.dark ? 1.9 : 1.3);
    key.position.set(-1.2, 1.4, 1.6);
    globe.lights([new AmbientLight(0xffffff, palette.dark ? 1.55 : 2.2)]);
    if (!camera.parent) scene.add(camera);
    camera.add(key);
    return () => {
      camera.remove(key);
      key.dispose();
    };
  }, [ready, palette.dark]);

  // ---- halo, starfield and the one animation loop that drives every
  // time-based effect (ocean rim + shimmer, halo hue, star twinkle + drift).
  useEffect(() => {
    const globe = globeRef.current;
    if (!globe || !ready) return;
    const scene = globe.scene();
    const camera = globe.camera();

    const haloTexture = glowTexture();
    const haloMaterial = new SpriteMaterial({
      map: haloTexture,
      transparent: true,
      depthWrite: false,
      opacity: palette.dark ? 0.55 : 0.32,
      blending: palette.dark ? AdditiveBlending : NormalBlending,
    });
    const halo = new Sprite(haloMaterial);
    halo.renderOrder = -1;
    scene.add(halo);

    const stars: Points[] = [];
    const starGeos: BufferGeometry[] = [];
    const starMats: PointsMaterial[] = [];
    if (palette.dark) {
      const faintGeo = starShell(compact ? 380 : 700, 7);
      const brightGeo = starShell(compact ? 60 : 110, 131);
      const faintMat = new PointsMaterial({
        size: 1,
        sizeAttenuation: false,
        transparent: true,
        opacity: 0.6,
        depthWrite: false,
        vertexColors: true,
      });
      const brightMat = new PointsMaterial({
        size: 2,
        sizeAttenuation: false,
        transparent: true,
        opacity: 0.85,
        depthWrite: false,
        vertexColors: true,
        blending: AdditiveBlending,
      });
      stars.push(new Points(faintGeo, faintMat), new Points(brightGeo, brightMat));
      starGeos.push(faintGeo, brightGeo);
      starMats.push(faintMat, brightMat);
      scene.add(...stars);
    }

    const hueColors = [0.08, 0.3, 0.5, 0.7, 0.92].map((t) => toColor(rampAt(ramp, t)));
    const tint = new Color();
    const paint = (seconds: number) => {
      OCEAN_TIME.value = seconds;
      // Halo: slow walk through the ramp hues, gently breathing.
      const x = (seconds / 7) % hueColors.length;
      const i = Math.floor(x);
      tint.copy(hueColors[i]).lerp(hueColors[(i + 1) % hueColors.length], x - i);
      haloMaterial.color.copy(tint);
      // Keep the halo just behind the globe as seen from the camera, scaled
      // up for the extra distance, so it only ever glows around the rim.
      const distance = camera.position.length() || 1;
      halo.position.copy(camera.position).multiplyScalar(-HALO_BACK / distance);
      const size = HALO_SIZE * ((distance + HALO_BACK) / distance) * (1 + Math.sin(seconds * 0.8) * 0.025);
      halo.scale.set(size, size, 1);
      if (starMats.length) {
        starMats[0].opacity = 0.5 + Math.sin(seconds * 0.9) * 0.12;
        starMats[1].opacity = 0.6 + Math.sin(seconds * 1.7 + 1.3) * 0.3;
        for (const s of stars) s.rotation.y = seconds * 0.004;
      }
    };

    // The loop also runs with reduced motion (time frozen at 0) so the
    // halo keeps following the camera when the user drags the globe.
    let frame = 0;
    const tick = (time: number) => {
      paint(reducedMotion ? 0 : time / 1000);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      scene.remove(halo, ...stars);
      haloMaterial.dispose();
      haloTexture.dispose();
      starGeos.forEach((g) => g.dispose());
      starMats.forEach((m) => m.dispose());
    };
  }, [ready, palette.dark, compact, reducedMotion, ramp]);

  // ---- camera: world vs focus, re-run when the data or view changes.
  // The first move is a slow fly-in from further out and a little to the west.
  const focusPoints = useMemo(
    () => (places.length ? places : regions.map((r) => ({ lat: r.lat, lon: r.lon }))),
    [places, regions],
  );
  useEffect(() => {
    const globe = globeRef.current;
    if (!globe || !ready) return;
    const target =
      view === "focus" && focusPoints.length
        ? focusFor(focusPoints, compact)
        : { ...focusFor(focusPoints, compact), altitude: compact ? 2.5 : 2.3 };
    if (!introPlayed.current) {
      introPlayed.current = true;
      if (!reducedMotion) {
        globe.pointOfView({ lat: target.lat - 12, lng: target.lng - 55, altitude: target.altitude + 1.5 }, 0);
        globe.pointOfView(target, 2600);
        return;
      }
    }
    globe.pointOfView(target, reducedMotion ? 0 : 1400);
  }, [view, focusPoints, compact, ready, reducedMotion]);

  // ---- controls: gentle auto-rotate that stops for good once the user grabs the globe
  useEffect(() => {
    const globe = globeRef.current;
    if (!globe || !ready) return;
    const controls = globe.controls();
    controls.autoRotate = autoRotate;
    controls.autoRotateSpeed = 0.32;
    controls.enableZoom = !compact; // inline cards must not hijack page scroll
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 0.7;
    controls.minDistance = 130;
    controls.maxDistance = 600;
    const stop = () => onUserInteract?.();
    controls.addEventListener("start", stop);
    return () => controls.removeEventListener("start", stop);
  }, [ready, autoRotate, compact, onUserInteract]);

  const setHover = (key: string | null) => {
    setHoverKey(key);
    onHoverPlace?.(key);
  };

  const tooltip = (place: GeoPlace | undefined, fallbackName?: string) => {
    if (!place) return fallbackName ? `<div class="qc-globe-tip"><strong>${escapeHtml(fallbackName)}</strong></div>` : "";
    const rank = rankOf.get(place.key);
    const sub = `${place.kind === "city" && place.country ? `${escapeHtml(place.country)} · ` : ""}${escapeHtml(place.continent)}`;
    const value =
      typeof place.value === "number"
        ? `<span class="qc-globe-tip__value">${escapeHtml(formatValue(place.value, format, false))}<em>${escapeHtml(metric ?? "")}</em></span>`
        : "";
    const share =
      typeof place.share === "number" ? `<span class="qc-globe-tip__share">${(place.share * 100).toFixed(1)}% of total</span>` : "";
    const badge =
      typeof place.value === "number" && rank
        ? `<span class="qc-globe-tip__rank" style="background:${placeColor(place)}">#${rank}</span>`
        : "";
    return `<div class="qc-globe-tip"><strong>${badge}${escapeHtml(place.name)}</strong><span class="qc-globe-tip__sub">${sub}</span>${value}${share}</div>`;
  };

  // ---- layer data
  const columnHeight = (place: GeoPlace) => {
    const t = level(place);
    return t == null ? 0.015 : 0.02 + t * (compact ? 0.28 : 0.36);
  };
  const labelPlaces = ranked.slice(0, compact ? 4 : 8);
  const ringPlaces = reducedMotion ? [] : ranked.slice(0, compact ? 3 : 5);

  // Light trails from the leader to the next places, each in its own colours.
  const arcs = useMemo<Arc[]>(() => {
    if (ranked.length < 2) return [];
    const [leader, ...rest] = ranked;
    const from = rampAt(ramp, level(leader) ?? 1);
    return rest.slice(0, compact ? 4 : 7).map((place, index) => ({
      startLat: leader.lat,
      startLng: leader.lon,
      endLat: place.lat,
      endLng: place.lon,
      colors: [from, rampAt(ramp, level(place) ?? 0.5)],
      order: index,
    }));
    // level() depends only on max, which follows ranked.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ranked, ramp, compact]);

  return (
    <Globe
      ref={globeRef}
      width={width}
      height={height}
      backgroundColor="rgba(0,0,0,0)"
      globeMaterial={globeMaterial}
      showGraticules={false}
      showAtmosphere
      atmosphereColor={palette.atmosphere}
      atmosphereAltitude={0.18}
      onGlobeReady={() => setReady(true)}
      // hex dots: rainbow halftone land for the countries the answer doesn't mention
      hexPolygonsData={dotted}
      hexPolygonResolution={compact ? 2 : 3}
      hexPolygonMargin={0.6}
      hexPolygonUseDots
      hexPolygonDotResolution={compact ? 5 : 8}
      hexPolygonAltitude={0.004}
      hexPolygonColor={(d) => dotColors.get(String((d as CountryFeature).id)) ?? palette.dot}
      hexPolygonLabel={(d) => tooltip(undefined, (d as CountryFeature).properties?.name)}
      hexPolygonsTransitionDuration={0}
      // polygons: 3D choropleth of the marked countries along the aurora ramp
      polygonsData={solid}
      polygonCapColor={(d) => {
        const id = String((d as CountryFeature).id);
        const place = byCountry.get(id);
        if (!place) return mix(palette.land, rampAt(ramp, 0.4), 0.35, 0.9);
        const active = activeKey === place.key || (activeKey?.startsWith("city:") && ranked.find((p) => p.key === activeKey)?.id === id);
        const base = placeColor(place);
        return active ? mix(base, "#ffffff", 0.35) : mix(palette.land, base, 0.82, 0.96);
      }}
      polygonSideColor={(d) => {
        const place = byCountry.get(String((d as CountryFeature).id));
        return place ? placeColor(place, 0.45) : mix(palette.land, rampAt(ramp, 0.4), 0.3, 0.35);
      }}
      polygonStrokeColor={(d) => {
        const place = byCountry.get(String((d as CountryFeature).id));
        return place ? mix(placeColor(place), "#ffffff", 0.5, 0.6) : palette.border;
      }}
      polygonAltitude={(d) => {
        const id = String((d as CountryFeature).id);
        const place = byCountry.get(id);
        if (!place) return 0.007;
        const t = level(place);
        const lift = t == null ? 0.016 : 0.012 + t * 0.045;
        return activeKey === place.key ? lift + 0.014 : lift;
      }}
      polygonLabel={(d) => {
        const feat = d as CountryFeature;
        return tooltip(byCountry.get(String(feat.id)), feat.properties?.name);
      }}
      onPolygonHover={(d) => {
        const place = d ? byCountry.get(String((d as CountryFeature).id)) : undefined;
        setHover(place?.kind === "country" ? place.key : null);
      }}
      polygonsTransitionDuration={reducedMotion ? 0 : 900}
      // arcs: animated light trails from the leader
      arcsData={arcs}
      arcStartLat={(d) => (d as Arc).startLat}
      arcStartLng={(d) => (d as Arc).startLng}
      arcEndLat={(d) => (d as Arc).endLat}
      arcEndLng={(d) => (d as Arc).endLng}
      arcColor={(d: object) => (d as Arc).colors}
      arcStroke={compact ? 0.32 : 0.45}
      arcAltitudeAutoScale={0.42}
      arcDashLength={reducedMotion ? 1 : 0.45}
      arcDashGap={reducedMotion ? 0 : 0.35}
      arcDashInitialGap={(d) => ((d as Arc).order * 0.17) % 1}
      arcDashAnimateTime={(d) => (reducedMotion ? 0 : 2600 + (d as Arc).order * 260)}
      arcsTransitionDuration={reducedMotion ? 0 : 1200}
      // points: slim value columns, coloured by value
      pointsData={ranked}
      pointLat={(d) => (d as GeoPlace).lat}
      pointLng={(d) => (d as GeoPlace).lon}
      pointAltitude={(d) => columnHeight(d as GeoPlace)}
      pointRadius={(d) => {
        const place = d as GeoPlace;
        const base = place.kind === "city" ? 0.24 : 0.38;
        return activeKey === place.key ? base * 1.45 : base;
      }}
      pointColor={(d) => {
        const place = d as GeoPlace;
        if (activeKey === place.key) return "#ffffff";
        return mix(placeColor(place), "#ffffff", 0.12, 0.95);
      }}
      pointResolution={20}
      pointsMerge={false}
      pointLabel={(d) => tooltip(d as GeoPlace)}
      onPointHover={(d) => setHover(d ? (d as GeoPlace).key : null)}
      pointsTransitionDuration={reducedMotion ? 0 : 1600}
      // rings: ripples under the leaders in each place's colour
      ringsData={ringPlaces}
      ringLat={(d) => (d as GeoPlace).lat}
      ringLng={(d) => (d as GeoPlace).lon}
      ringColor={(d: object) => {
        const color = placeColor(d as GeoPlace);
        return (t: number) => mix(color, "#ffffff", t * 0.4, Math.max(0, 1 - t) ** 1.5 * 0.8);
      }}
      ringMaxRadius={(d) => 2.5 + (level(d as GeoPlace) ?? 0.4) * 3.5}
      ringPropagationSpeed={1.2}
      ringRepeatPeriod={(d) => 2200 + ((rankOf.get((d as GeoPlace).key) ?? 1) - 1) * 340}
      ringAltitude={0.005}
      // html: ranked labels for the leaders
      htmlElementsData={labelPlaces}
      htmlLat={(d) => (d as GeoPlace).lat}
      htmlLng={(d) => (d as GeoPlace).lon}
      htmlAltitude={(d) => columnHeight(d as GeoPlace) + 0.01}
      htmlElement={(d) => {
        const place = d as GeoPlace;
        const rank = rankOf.get(place.key) ?? 0;
        const el = document.createElement("div");
        el.className = "qc-globe-label";
        const body = document.createElement("div");
        body.className = "qc-globe-label__body";
        body.style.setProperty("--i", String(rank - 1));
        body.style.setProperty("--place", placeColor(place));
        if (typeof place.value === "number") {
          const badge = document.createElement("i");
          badge.textContent = String(rank);
          body.appendChild(badge);
        }
        const name = document.createElement("span");
        name.textContent = place.name;
        body.appendChild(name);
        if (!compact && typeof place.value === "number") {
          const value = document.createElement("b");
          value.textContent = formatValue(place.value, format);
          body.appendChild(value);
        }
        el.appendChild(body);
        return el;
      }}
      htmlElementVisibilityModifier={(el, visible) => {
        el.style.opacity = visible ? "1" : "0";
      }}
      htmlTransitionDuration={600}
    />
  );
}
