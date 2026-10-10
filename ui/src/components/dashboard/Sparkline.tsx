/**
 * A tile's small trend line: one series, no axes, no legend — the tile's
 * label names it and the figure beside it is the value. Neutral ink, not a
 * status color: "names scanned" going up is not good news or bad news.
 * The last reading gets a dot so the eye lands on "now".
 */
export function Sparkline({ values, width = 96, height = 28 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) {
    return <span className="t-meta text-ink-faint">one run so far</span>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 3;
  const x = (i: number) => pad + (i / (values.length - 1)) * (width - pad * 2);
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2);
  const d = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = values.length - 1;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="shrink-0">
      <path d={d} fill="none" stroke="var(--color-ink-dim)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={x(last)} cy={y(values[last])} r="2.5" fill="var(--color-ink)" />
    </svg>
  );
}
