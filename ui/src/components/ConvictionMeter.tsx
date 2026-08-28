/**
 * One conviction widget, reused everywhere a 0-100 score shows up (Actions
 * cards, Research memos, Positions cards, the Book table) so "conviction"
 * reads the same way across the whole app instead of a different number
 * format per screen. Color bands reuse the app's existing reserved
 * gain/risk/loss tokens (dataviz "status palette" job) rather than
 * introducing a new scale — >=70 strong, 40-69 mixed, <40 weak.
 */
function band(score: number): "gain" | "risk" | "loss" {
  if (score >= 70) return "gain";
  if (score >= 40) return "risk";
  return "loss";
}

const BAR_COLOR = {
  gain: "bg-[var(--color-gain)]",
  risk: "bg-[var(--color-risk)]",
  loss: "bg-[var(--color-loss)]",
};

const TEXT_COLOR = {
  gain: "text-[var(--color-gain)]",
  risk: "text-[var(--color-risk)]",
  loss: "text-[var(--color-loss)]",
};

export function ConvictionMeter({
  score,
  size = "md",
  label = "Conviction",
}: {
  score: number;
  size?: "sm" | "md";
  label?: string | null;
}) {
  const tone = band(score);
  const pct = Math.min(Math.max(score, 0), 100);
  const barHeight = size === "sm" ? "h-1.5" : "h-2";

  return (
    <div className="flex min-w-[7rem] flex-1 items-center gap-2">
      {label && <span className="shrink-0 text-xs text-[var(--color-ink-faint)]">{label}</span>}
      <div className={`relative ${barHeight} flex-1 rounded-full bg-[var(--color-hairline)]`}>
        <div className={`absolute inset-y-0 left-0 rounded-full ${BAR_COLOR[tone]}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`num shrink-0 text-sm font-semibold ${TEXT_COLOR[tone]}`}>{Math.round(score)}</span>
    </div>
  );
}
