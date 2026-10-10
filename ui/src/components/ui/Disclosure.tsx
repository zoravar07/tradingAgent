import { useId, useState } from "react";
import { CaretDown } from "@phosphor-icons/react";
import clsx from "clsx";
import type { ReactNode } from "react";
import { Term } from "./Term";

/**
 * The reference's "View full rationale & details" footer: a full-width
 * control across the bottom of a card that expands the long-form content
 * in place.
 *
 * This is deliberately not a drawer. A thesis paragraph inline pushes every
 * following card below the fold, so the previous build put long prose behind
 * a right-side Sheet — but the reference asks for the argument to open where
 * it sits, and an expander keeps it out of the scannable list without moving
 * the reader somewhere else. The Sheet stays available for genuinely long
 * multi-section analysis (Insights), and this handles the common case.
 *
 * The open/close transition runs on `grid-template-rows: 0fr → 1fr`, the
 * only way to transition to an unknown content height without animating
 * `height` itself.
 */
export function Disclosure({
  label,
  openLabel,
  children,
  defaultOpen = false,
}: {
  label: string;
  /** Label once open — defaults to the same string. */
  openLabel?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="pressable flex w-full items-center justify-center gap-sp-2 px-sp-6 py-sp-4 t-body font-medium text-ink-dim hover:bg-inset-strong hover:text-ink"
      >
        <CaretDown
          size={15}
          weight="bold"
          className={clsx(
            "transition-transform duration-[var(--dur-expand)] ease-out motion-reduce:transition-none",
            open && "rotate-180",
          )}
        />
        {open ? (openLabel ?? label) : label}
      </button>

      <div id={panelId} className="expandable" data-open={open}>
        <div>
          <div className="border-t border-line bg-surface px-sp-6 py-sp-5">{children}</div>
        </div>
      </div>
    </>
  );
}

/**
 * A labelled block inside a disclosure — the unit long-form detail is built
 * from.
 *
 * `define` glosses the LABEL, never the body. Glossing a term inside prose
 * that sits under a heading of the same word prints it twice ("Thesis /
 * Thesis: AMD has...").
 */
export function DetailBlock({
  label,
  tone,
  define,
  children,
}: {
  label: string;
  tone?: "loss";
  define?: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-sp-2">
      <h4 className={clsx("t-title", tone === "loss" ? "text-loss" : "text-ink")}>
        {define ? <Term text={label} definition={define} /> : label}
      </h4>
      <div className="t-body max-w-[78ch] text-ink-dim">{children}</div>
    </section>
  );
}
