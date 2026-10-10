import { cva, type VariantProps } from "class-variance-authority";
import clsx from "clsx";
import type { ReactNode } from "react";

/**
 * The reference's action chip ("SELL / TRIM"): uppercase, letterspaced,
 * semantic wash behind semantic text. Every status on every screen uses this
 * one component, so a red chip means the same thing on Orders as it does on
 * Briefing.
 */
const pill = cva(
  "inline-flex items-center gap-sp-1 whitespace-nowrap rounded-chip px-sp-3 py-[5px] t-pill",
  {
    variants: {
      tone: {
        buy: "bg-gain-wash text-gain",
        sell: "bg-loss-wash text-loss",
        gain: "bg-gain-wash text-gain",
        loss: "bg-loss-wash text-loss",
        risk: "bg-risk-wash text-risk",
        accent: "bg-accent-wash text-accent",
        neutral: "bg-inset-strong text-ink-dim",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function StatusPill({
  tone,
  className,
  children,
}: VariantProps<typeof pill> & { className?: string; children: ReactNode }) {
  return <span className={clsx(pill({ tone }), className)}>{children}</span>;
}

/** Sentence-case sibling for labels that aren't statuses — a source, a count. */
export function Tag({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-sp-1 whitespace-nowrap rounded-chip bg-inset-strong px-sp-2 py-[3px] t-meta text-ink-dim",
        className,
      )}
    >
      {children}
    </span>
  );
}
