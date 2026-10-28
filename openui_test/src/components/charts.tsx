"use client";

import { useMemo, useRef, useState } from "react";
import { area, curveMonotoneX, line } from "d3-shape";
import { scaleLinear } from "d3-scale";

import { formatValue, type ValueFormat } from "@/lib/geo";

/**
 * Small dependency-light SVG charts for the Insights pages. Thin marks,
 * recessive grid, values in text ink (never the series color) and a hover
 * layer on every mark.
 */

export type Row = { label: string; value: number };

const SERIES = Array.from({ length: 8 }, (_, i) => `var(--qc-series-${i + 1})`);

/** Horizontal ranked bars: magnitude in one hue, labels left, values right. */
export function BarList({
  rows,
  format = "number",
  highlight,
  onHover,
  max: maxRows = 10,
}: {
  rows: Row[];
  format?: ValueFormat;
  highlight?: string | null;
  onHover?: (label: string | null) => void;
  max?: number;
}) {
  const shown = [...rows].sort((a, b) => b.value - a.value).slice(0, maxRows);
  const top = shown[0]?.value || 1;
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  return (
    <ol className="qc-barlist">
      {shown.map((row, index) => (
        <li
          key={row.label}
          className={`qc-barlist__row ${highlight === row.label ? "is-active" : ""}`}
          onPointerEnter={() => onHover?.(row.label)}
          onPointerLeave={() => onHover?.(null)}
          title={`${row.label}: ${formatValue(row.value, format, false)}${total ? ` (${((row.value / total) * 100).toFixed(1)}%)` : ""}`}
        >
          <span className="qc-barlist__rank">{index + 1}</span>
          <span className="qc-barlist__label">{row.label}</span>
          <span className="qc-barlist__value">{formatValue(row.value, format)}</span>
          <span className="qc-barlist__track" aria-hidden="true">
            <span className="qc-barlist__bar" style={{ width: `${Math.max(2, (row.value / top) * 100)}%` }} />
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Donut for part-to-whole with ≤ 6 parts; legend doubles as direct labels. */
export function Donut({ rows, format = "number", centerLabel }: { rows: Row[]; format?: ValueFormat; centerLabel?: string }) {
  const [active, setActive] = useState<number | null>(null);
  const parts = rows.slice(0, 6);
  const total = parts.reduce((sum, row) => sum + row.value, 0) || 1;
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const gap = parts.length > 1 ? 3 : 0;
  const offsets = parts.map((_, index) =>
    parts.slice(0, index).reduce((sum, part) => sum + (part.value / total) * circumference, 0),
  );
  const focus = active != null ? parts[active] : null;

  return (
    <div className="qc-donut">
      <svg viewBox="0 0 140 140" className="qc-donut__svg" role="img" aria-label={parts.map((p) => `${p.label} ${formatValue(p.value, format)}`).join(", ")}>
        <circle cx="70" cy="70" r={radius} className="qc-donut__track" />
        {parts.map((part, index) => {
          const length = (part.value / total) * circumference;
          const dash = Math.max(0.5, length - gap);
          return (
            <circle
              key={part.label}
              cx="70"
              cy="70"
              r={radius}
              className={`qc-donut__segment ${active === index ? "is-active" : ""}`}
              stroke={SERIES[index]}
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-offsets[index]}
              onPointerEnter={() => setActive(index)}
              onPointerLeave={() => setActive(null)}
            />
          );
        })}
        <text x="70" y="66" textAnchor="middle" className="qc-donut__center-value">
          {focus ? `${((focus.value / total) * 100).toFixed(0)}%` : formatValue(total, format)}
        </text>
        <text x="70" y="84" textAnchor="middle" className="qc-donut__center-label">
          {focus ? focus.label.slice(0, 16) : centerLabel ?? "Total"}
        </text>
      </svg>
      <ul className="qc-donut__legend">
        {parts.map((part, index) => (
          <li
            key={part.label}
            className={active === index ? "is-active" : ""}
            onPointerEnter={() => setActive(index)}
            onPointerLeave={() => setActive(null)}
          >
            <span className="qc-swatch" style={{ background: SERIES[index] }} />
            <span className="qc-donut__legend-label">{part.label}</span>
            <span className="qc-donut__legend-value">{formatValue(part.value, format)}</span>
            <span className="qc-donut__legend-share">{((part.value / total) * 100).toFixed(0)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Area + 2px line with a crosshair tooltip, for change over time. */
export function TrendChart({ rows, format = "number", height = 220 }: { rows: Row[]; format?: ValueFormat; height?: number }) {
  const width = 640;
  const pad = { top: 16, right: 16, bottom: 28, left: 52 };
  const ref = useRef<SVGSVGElement>(null);
  const [index, setIndex] = useState<number | null>(null);

  const { x, y, linePath, areaPath, ticks } = useMemo(() => {
    const values = rows.map((r) => r.value);
    const x = scaleLinear().domain([0, Math.max(1, rows.length - 1)]).range([pad.left, width - pad.right]);
    const y = scaleLinear().domain([0, Math.max(...values, 1) * 1.08]).nice(4).range([height - pad.bottom, pad.top]);
    const linePath = line<Row>().x((_, i) => x(i)).y((d) => y(d.value)).curve(curveMonotoneX)(rows) ?? "";
    const areaPath = area<Row>().x((_, i) => x(i)).y0(y(0)).y1((d) => y(d.value)).curve(curveMonotoneX)(rows) ?? "";
    return { x, y, linePath, areaPath, ticks: y.ticks(4) };
  }, [rows, height, pad.left, pad.right, pad.top, pad.bottom]);

  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box || rows.length === 0) return;
    const px = ((event.clientX - box.left) / box.width) * width;
    setIndex(Math.max(0, Math.min(rows.length - 1, Math.round(x.invert(px)))));
  };

  const every = Math.ceil(rows.length / 8);
  const point = index != null ? rows[index] : null;

  return (
    <div className="qc-trend">
      <svg
        ref={ref}
        viewBox={`0 0 ${width} ${height}`}
        className="qc-trend__svg"
        role="img"
        aria-label={rows.map((r) => `${r.label} ${formatValue(r.value, format)}`).join(", ")}
        onPointerMove={onMove}
        onPointerLeave={() => setIndex(null)}
      >
        <defs>
          <linearGradient id="qc-trend-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--qc-accent)" stopOpacity="0.32" />
            <stop offset="100%" stopColor="var(--qc-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} className="qc-trend__grid" />
            <text x={pad.left - 8} y={y(tick) + 4} textAnchor="end" className="qc-trend__axis">
              {formatValue(tick, format)}
            </text>
          </g>
        ))}
        {rows.map((row, i) =>
          i % every === 0 || i === rows.length - 1 ? (
            <text key={row.label} x={x(i)} y={height - 8} textAnchor="middle" className="qc-trend__axis">
              {row.label}
            </text>
          ) : null,
        )}
        <path d={areaPath} fill="url(#qc-trend-fill)" />
        <path d={linePath} className="qc-trend__line" />
        {point && index != null && (
          <g>
            <line x1={x(index)} x2={x(index)} y1={pad.top} y2={height - pad.bottom} className="qc-trend__cross" />
            <circle cx={x(index)} cy={y(point.value)} r={5} className="qc-trend__dot" />
          </g>
        )}
      </svg>
      {point && index != null && (
        <div className="qc-trend__tooltip" style={{ left: `${(x(index) / width) * 100}%` }}>
          <span>{point.label}</span>
          <strong>{formatValue(point.value, format, false)}</strong>
        </div>
      )}
    </div>
  );
}

/** Tiny inline sparkline for insight cards. */
export function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const w = 96;
  const h = 28;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const sx = (i: number) => (i / (values.length - 1)) * w;
  const sy = (v: number) => h - 3 - ((v - min) / (max - min || 1)) * (h - 6);
  const d = values.map((v, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join("");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="qc-spark" aria-hidden="true">
      <path d={d} />
      <circle cx={sx(values.length - 1)} cy={sy(values[values.length - 1])} r={2.5} />
    </svg>
  );
}
