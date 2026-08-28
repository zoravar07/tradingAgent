import type { Icon } from "@phosphor-icons/react";
import { HelpTip } from "./HelpTip";

type Tone = "gain" | "loss" | "risk" | "accent";

const TEXT_CLASSES: Record<Tone, string> = {
  gain: "text-[var(--color-gain)]",
  loss: "text-[var(--color-loss)]",
  risk: "text-[var(--color-risk)]",
  accent: "text-[var(--color-accent)]",
};

const WASH_CLASSES: Record<Tone, string> = {
  gain: "bg-[var(--color-gain-wash)]",
  loss: "bg-[var(--color-loss-wash)]",
  risk: "bg-[var(--color-risk-wash)]",
  accent: "bg-[var(--color-accent-wash)]",
};

/**
 * A single "read in one glance" number for a summary strip — dataviz's
 * hero-number pattern: big bold value, small label above it, an icon chip
 * for visual anchoring, color only when the value itself carries a status.
 */
export function StatTile({
  label,
  value,
  tone,
  help,
  icon: TileIcon,
}: {
  label: string;
  value: string;
  tone?: Tone;
  help?: string;
  icon?: Icon;
}) {
  return (
    <div className="flex min-w-[9.5rem] flex-1 items-center gap-3 px-5 py-4">
      {TileIcon && (
        <span
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
            tone ? WASH_CLASSES[tone] : "bg-[var(--color-panel-raised)]"
          }`}
        >
          <TileIcon size={16} weight="bold" className={tone ? TEXT_CLASSES[tone] : "text-[var(--color-ink-dim)]"} />
        </span>
      )}
      <div className="flex flex-col gap-1">
        <span className="flex items-center gap-1 text-xs text-[var(--color-ink-faint)]">
          {label}
          {help && <HelpTip text={help} />}
        </span>
        <span className={`num text-2xl leading-none font-semibold ${tone ? TEXT_CLASSES[tone] : "text-[var(--color-ink)]"}`}>
          {value}
        </span>
      </div>
    </div>
  );
}
