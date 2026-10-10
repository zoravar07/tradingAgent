import clsx from "clsx";
import type { ReactNode } from "react";
import { fmtLongDate } from "../../lib/format";

/**
 * The frame every screen shares. This is the single biggest reason eight
 * screens read as one product rather than eight: identical header geometry,
 * identical gutter, identical max-width, identical section rhythm. No screen
 * sets its own page padding.
 *
 * The header is the reference's: a large title on the left with a
 * supporting line under it, and the date on the right. It scrolls with the
 * page rather than sticking — at 34px a pinned header eats a third of a
 * laptop viewport, and the reference doesn't pin it either.
 */
export function ScreenShell({
  title,
  subtitle,
  actions,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  /** Trailing controls under the date — Refresh, Save. */
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-[1180px] flex-col gap-sp-6 px-sp-7 py-sp-7">
        <header className="flex flex-wrap items-start justify-between gap-sp-5">
          <div className="min-w-0">
            <h1 className="t-hero text-ink">{title}</h1>
            {subtitle && <p className="mt-sp-2 t-lead text-ink-dim">{subtitle}</p>}
          </div>
          {/* ml-auto keeps this hugging the right edge even when the header
              wraps — without it a wide actions row (Settings has four
              controls) drops to its own line and drags the date left with
              it, so the date appears to move when a status pill shows up. */}
          <div className="ml-auto flex shrink-0 flex-col items-end gap-sp-3">
            <p className="t-body text-ink-dim">{fmtLongDate(new Date())}</p>
            {actions}
          </div>
        </header>

        {children}
      </div>
    </div>
  );
}

/**
 * A titled region within a screen. Bare by default — no card chrome — so a
 * section of cards doesn't become a card containing cards.
 */
export function Section({
  title,
  subtitle,
  icon,
  count,
  actions,
  children,
  className,
}: {
  title: string;
  subtitle?: ReactNode;
  /** Small leading glyph, as the reference sets beside "Proposed Trade". */
  icon?: ReactNode;
  count?: number;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={clsx("flex flex-col gap-sp-4", className)}>
      <div className="flex flex-wrap items-center justify-between gap-sp-3">
        <div className="flex items-center gap-sp-3">
          {icon}
          <h2 className="t-title text-ink">{title}</h2>
          {count !== undefined && (
            <span className="num-table rounded-chip bg-inset-strong px-sp-2 py-[2px] t-meta font-medium text-ink-dim">
              {count}
            </span>
          )}
        </div>
        {actions}
      </div>
      {subtitle && <p className="-mt-sp-2 max-w-[76ch] t-body text-ink-faint">{subtitle}</p>}
      {children}
    </section>
  );
}

/** The "nothing here, and that's a real answer" row. */
export function EmptyRow({ label, hint }: { label: string; hint?: string }) {
  return (
    <div className="rounded-card border border-dashed border-line px-sp-6 py-sp-8 text-center">
      <p className="t-body font-medium text-ink-dim">{label}</p>
      {hint && <p className="mt-sp-1 t-meta text-ink-faint">{hint}</p>}
    </div>
  );
}
