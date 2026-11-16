"use client";

import type { components } from "@/lib/api/schema";

type Result = components["schemas"]["ReportResult"];

const COLOURS = ["#6366f1", "#14b8a6", "#f59e0b", "#ef4444", "#8b5cf6", "#22c55e", "#ec4899", "#0ea5e9", "#a3a3a3"];

/** Charts for reports, drawn by Core itself (Decision log #35: no chart library). Money in
 * several currencies is never drawn on one scale: the first currency is charted, the table
 * shows them all. */
export function ReportChart({ result, display, format }: { result: Result; display: string; format: (v: number, currency?: string | null) => string }) {
  const firstCurrency = result.rows.find((r) => r.currency)?.currency ?? null;
  const rows = result.rows.filter((r) => !result.money || r.currency === firstCurrency).slice(0, 60);
  const items = rows.map((r) => ({ label: r.labels.join(" · ") || "Total", value: Number(r.value), currency: r.currency }));
  const several = result.money && new Set(result.rows.map((r) => r.currency)).size > 1;
  const note = several ? <p className="text-xs text-muted-foreground">Chart shows {firstCurrency} only; the table has every currency.</p> : null;
  if (display === "pie") return <>{note}<Pie items={items} format={format} /></>;
  if (display === "line") return <>{note}<Line items={items} format={format} /></>;
  return <>{note}<Bars items={items} format={format} /></>;
}

type Item = { label: string; value: number; currency?: string | null };
type Fmt = (v: number, currency?: string | null) => string;

function Bars({ items, format }: { items: Item[]; format: Fmt }) {
  const max = Math.max(1, ...items.map((i) => Math.abs(i.value)));
  return (
    <ul className="space-y-1.5 text-xs">
      {items.map((i, n) => (
        <li key={n} className="flex items-center gap-2">
          <span className="w-40 shrink-0 truncate" title={i.label}>
            {i.label}
          </span>
          <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
            <span className="block h-full rounded-full bg-primary" style={{ width: `${(Math.abs(i.value) / max) * 100}%` }} />
          </span>
          <span className="min-w-24 shrink-0 text-right tabular-nums">{format(i.value, i.currency)}</span>
        </li>
      ))}
    </ul>
  );
}

function Line({ items, format }: { items: Item[]; format: Fmt }) {
  const w = 640;
  const h = 200;
  const pad = 24;
  const max = Math.max(1, ...items.map((i) => i.value));
  const step = items.length > 1 ? (w - pad * 2) / (items.length - 1) : 0;
  const points = items.map((i, n) => [pad + n * step, h - pad - (i.value / max) * (h - pad * 2)] as const);
  return (
    <figure className="space-y-1">
      <svg viewBox={`0 0 ${w} ${h}`} className="h-52 w-full" role="img" aria-label="Line chart">
        <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} className="stroke-border" />
        <polyline fill="none" className="stroke-primary" strokeWidth={2} points={points.map((p) => p.join(",")).join(" ")} />
        {points.map(([x, y], n) => (
          <circle key={n} cx={x} cy={y} r={3} className="fill-primary">
            <title>{`${items[n].label}: ${format(items[n].value, items[n].currency)}`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="flex justify-between text-xs text-muted-foreground">
        <span>{items[0]?.label}</span>
        <span>{items[items.length - 1]?.label}</span>
      </figcaption>
    </figure>
  );
}

function Pie({ items, format }: { items: Item[]; format: Fmt }) {
  const positive = items.filter((i) => i.value > 0);
  const top = positive.slice(0, 8);
  const rest = positive.slice(8).reduce((s, i) => s + i.value, 0);
  const slices = rest > 0 ? [...top, { label: "Others", value: rest, currency: top[0]?.currency }] : top;
  const total = slices.reduce((s, i) => s + i.value, 0) || 1;
  const sizes = slices.map((s) => (s.value / total) * Math.PI * 2);
  const starts = sizes.map((_, n) => -Math.PI / 2 + sizes.slice(0, n).reduce((x, y) => x + y, 0));
  const arcs = slices.map((s, n) => {
    const a = sizes[n];
    const [x1, y1] = [50 + 45 * Math.cos(starts[n]), 50 + 45 * Math.sin(starts[n])];
    const [x2, y2] = [50 + 45 * Math.cos(starts[n] + a), 50 + 45 * Math.sin(starts[n] + a)];
    const d = slices.length === 1 ? "M50,5 A45,45 0 1,1 49.99,5 Z" : `M50,50 L${x1},${y1} A45,45 0 ${a > Math.PI ? 1 : 0},1 ${x2},${y2} Z`;
    return { d, colour: COLOURS[n % COLOURS.length], ...s };
  });
  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg viewBox="0 0 100 100" className="size-44 shrink-0" role="img" aria-label="Pie chart">
        {arcs.map((a, n) => (
          <path key={n} d={a.d} fill={a.colour}>
            <title>{`${a.label}: ${format(a.value, a.currency)}`}</title>
          </path>
        ))}
      </svg>
      <ul className="space-y-1 text-xs">
        {arcs.map((a, n) => (
          <li key={n} className="flex items-center gap-2">
            <span className="size-2.5 rounded-sm" style={{ background: a.colour }} />
            <span className="truncate">{a.label}</span>
            <span className="tabular-nums text-muted-foreground">
              {format(a.value, a.currency)} ({Math.round((a.value / total) * 100)}%)
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
