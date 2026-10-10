import { useId, useState } from "react";
import { fmtDateTime, fmtUsd } from "../../lib/format";

export interface LinePoint {
  x: string; // ISO timestamp
  y: number;
  label?: string;
}

const W = 900;
const H = 260;
const PAD = { top: 16, right: 16, bottom: 32, left: 64 };

/**
 * A single-series line chart, drawn as inline SVG. No chart library: one
 * series with a handful of points does not justify a dependency, and an SVG
 * we own is the only way to keep the axis, the marks and the tooltip on the
 * same design tokens as everything else.
 *
 * dataviz rules that are load-bearing here:
 *
 * - **The y-axis is not zero-based, and says so.** These are NAV readings
 *   within a narrow band; forcing zero would flatten every real movement
 *   into a straight line. The caption states the range so a reader can't
 *   mistake the visual slope for the magnitude.
 * - **Points are drawn, not just the line.** With four readings the line
 *   between them is interpolation, not data — the dots are what's real.
 * - **Time on x is spaced by actual elapsed time**, not by index, so two
 *   runs an hour apart don't read as the same gap as two runs a day apart.
 */
export function LineChart({
  points,
  caption,
}: {
  points: LinePoint[];
  caption?: string;
}) {
  const gradientId = useId();
  const [hover, setHover] = useState<number | null>(null);

  const times = points.map((p) => new Date(p.x).getTime());
  const values = points.map((p) => p.y);
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const vMin = Math.min(...values);
  const vMax = Math.max(...values);
  // A flat series would give a zero-height band and divide by zero; pad it
  // to a visible sliver instead so the line renders down the middle.
  const span = vMax - vMin || Math.max(vMax * 0.02, 1);
  const yLo = vMin - span * 0.15;
  const yHi = vMax + span * 0.15;

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const sx = (t: number) => PAD.left + (tMax === tMin ? plotW / 2 : ((t - tMin) / (tMax - tMin)) * plotW);
  const sy = (v: number) => PAD.top + plotH - ((v - yLo) / (yHi - yLo)) * plotH;

  const coords = points.map((p, i) => ({ x: sx(times[i]), y: sy(p.y), point: p }));
  const linePath = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x},${c.y}`).join(" ");
  const areaPath = `${linePath} L${coords[coords.length - 1].x},${PAD.top + plotH} L${coords[0].x},${PAD.top + plotH} Z`;

  // Time-proportional spacing means points can bunch — two runs 25 minutes
  // apart sit almost on top of each other next to one a day later. Drawing
  // every label there produces overlapping text, so a label is kept only if
  // it clears the last one drawn. The dots stay; only the words are thinned.
  const MIN_LABEL_GAP = 70;
  const labelled = new Set<number>();
  let lastLabelX = -Infinity;
  coords.forEach((c, i) => {
    if (c.x - lastLabelX >= MIN_LABEL_GAP) {
      labelled.add(i);
      lastLabelX = c.x;
    }
  });
  // The final point is the one a reader looks for, so it always keeps its
  // label — dropping an earlier one if that is what it takes to fit.
  const lastIndex = coords.length - 1;
  if (!labelled.has(lastIndex)) {
    for (const i of [...labelled].reverse()) {
      if (coords[lastIndex].x - coords[i].x < MIN_LABEL_GAP) labelled.delete(i);
      else break;
    }
    labelled.add(lastIndex);
  }

  const ticks = [yLo, (yLo + yHi) / 2, yHi];
  const rising = values[values.length - 1] >= values[0];
  const stroke = rising ? "var(--color-gain)" : "var(--color-loss)";

  const active = hover === null ? null : coords[hover];

  return (
    <figure className="flex flex-col gap-sp-3">
      <div className="relative w-full">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          role="img"
          aria-label={`Portfolio value over time, ${points.length} readings from ${fmtUsd(vMin)} to ${fmtUsd(vMax)}`}
          onMouseLeave={() => setHover(null)}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity="0.14" />
              <stop offset="100%" stopColor={stroke} stopOpacity="0" />
            </linearGradient>
          </defs>

          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={sy(t)}
                y2={sy(t)}
                stroke="var(--color-line)"
                strokeWidth="1"
              />
              <text
                x={PAD.left - 10}
                y={sy(t)}
                textAnchor="end"
                dominantBaseline="middle"
                fill="var(--color-ink-faint)"
                fontSize="12"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {fmtUsd(t)}
              </text>
            </g>
          ))}

          <path d={areaPath} fill={`url(#${gradientId})`} />
          <path
            d={linePath}
            fill="none"
            stroke={stroke}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {coords.map((c, i) => (
            <g key={i}>
              <circle
                cx={c.x}
                cy={c.y}
                r={hover === i ? 6 : 4}
                fill="var(--color-surface)"
                stroke={stroke}
                strokeWidth="2"
              />
              {/* Generous invisible hit area — a 4px dot is not a target. */}
              <rect
                x={c.x - plotW / (coords.length * 2) - 8}
                y={PAD.top}
                width={plotW / coords.length + 16}
                height={plotH}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
              />
            </g>
          ))}

          {coords.map((c, i) =>
            labelled.has(i) ? (
              <text
                key={`label-${i}`}
                x={Math.min(Math.max(c.x, PAD.left), W - PAD.right)}
                y={H - 10}
                textAnchor="middle"
                fill="var(--color-ink-faint)"
                fontSize="12"
              >
                {c.point.label ?? ""}
              </text>
            ) : null,
          )}
        </svg>

        {active && (
          <div
            className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-inner border border-line bg-surface px-sp-3 py-sp-2 shadow-card"
            style={{
              left: `${(active.x / W) * 100}%`,
              top: `${(active.y / H) * 100}%`,
              marginTop: "-10px",
            }}
          >
            <p className="num-table t-body font-semibold text-ink">{fmtUsd(active.point.y)}</p>
            <p className="t-meta text-ink-faint">{fmtDateTime(active.point.x)}</p>
          </div>
        )}
      </div>

      {caption && <figcaption className="t-meta text-ink-faint">{caption}</figcaption>}
    </figure>
  );
}
