import { HelpTip } from "./HelpTip";

type Tone = "gain" | "loss" | "risk" | "accent";

const TONE_CLASSES: Record<Tone, string> = {
  gain: "text-[var(--color-gain)]",
  loss: "text-[var(--color-loss)]",
  risk: "text-[var(--color-risk)]",
  accent: "text-[var(--color-accent)]",
};

/**
 * A single "read in one glance" number for a summary strip — dataviz's
 * hero-number pattern: big bold value, small label above it, color only
 * when the value itself carries a status (gain/loss/risk), never decorative.
 */
export function StatTile({
  label,
  value,
  tone,
  help,
}: {
  label: string;
  value: string;
  tone?: Tone;
  help?: string;
}) {
  return (
    <div className="flex min-w-[8.5rem] flex-1 flex-col gap-1 px-5 py-3.5">
      <span className="flex items-center gap-1 text-xs text-[var(--color-ink-faint)]">
        {label}
        {help && <HelpTip text={help} />}
      </span>
      <span className={`num text-2xl leading-none font-semibold ${tone ? TONE_CLASSES[tone] : "text-[var(--color-ink)]"}`}>
        {value}
      </span>
    </div>
  );
}
