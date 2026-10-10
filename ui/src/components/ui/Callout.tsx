import type { Icon } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import clsx from "clsx";

const TONE = {
  accent: {
    box: "border-accent-line bg-accent-wash",
    icon: "text-accent",
    title: "text-ink",
    body: "text-ink-dim",
  },
  risk: {
    box: "border-risk/25 bg-risk-wash",
    icon: "text-risk",
    title: "text-ink",
    body: "text-ink-dim",
  },
  loss: {
    box: "border-loss/25 bg-loss-wash",
    icon: "text-loss",
    title: "text-ink",
    body: "text-ink-dim",
  },
} as const;

/**
 * The reference's soft highlighted box: a tinted panel with an icon, a bold
 * line, a supporting line, and an optional outlined action on the right.
 *
 * Used for the things that are advice rather than data — a reminder about
 * process, a warning that the book is drifting from the broker. Keeping
 * those in a tinted box is what stops them being mistaken for another
 * figure to read.
 */
export function Callout({
  icon: CalloutIcon,
  title,
  children,
  action,
  tone = "accent",
  className,
}: {
  icon: Icon;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  tone?: keyof typeof TONE;
  className?: string;
}) {
  const t = TONE[tone];
  return (
    <div
      className={clsx(
        "flex flex-wrap items-center gap-sp-5 rounded-card border px-sp-6 py-sp-5",
        t.box,
        className,
      )}
    >
      <CalloutIcon size={30} weight="duotone" className={clsx("shrink-0", t.icon)} />
      <div className="min-w-[16rem] flex-1">
        <p className={clsx("t-lead font-semibold", t.title)}>{title}</p>
        {children && <p className={clsx("t-lead", t.body)}>{children}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
