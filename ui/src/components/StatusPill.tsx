type Tone = "gain" | "loss" | "risk" | "accent" | "neutral";

const TONE_CLASSES: Record<Tone, string> = {
  gain: "bg-[var(--color-gain-wash)] text-[var(--color-gain)]",
  loss: "bg-[var(--color-loss-wash)] text-[var(--color-loss)]",
  risk: "bg-[var(--color-risk-wash)] text-[var(--color-risk)]",
  accent: "bg-[var(--color-accent-wash)] text-[var(--color-accent)]",
  neutral: "bg-[var(--color-panel-raised)] text-[var(--color-ink-dim)]",
};

export function StatusPill({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
