import { useEffect, useState } from "react";
import clsx from "clsx";
import { Info } from "@phosphor-icons/react";
import { GLOSSARY } from "../../lib/glossary";

/**
 * Mirrors config.yaml's risk.min_hold_conviction default (Settings → "Min
 * hold conviction (floor)"). Below this the score itself becomes an action
 * trigger — the position is sold whatever the price is doing.
 */
const HOLD_FLOOR = 40;

/** Above this the reference calls a score "High conviction". */
const HIGH = 65;

interface Band {
  label: string;
  text: string;
  fill: string;
}

/**
 * Three bands, and the words and the color always agree. The reference reads
 * the number out loud ("High conviction") next to a green bar, so a ramp
 * that stayed one neutral hue would leave the label doing work the bar
 * contradicts.
 *
 * The floor band is red because that is where the score stops being a
 * measurement and becomes an instruction — the one point conviction earns a
 * status color.
 */
function bandFor(score: number): Band {
  if (score < HOLD_FLOOR) {
    return { label: "Below conviction floor", text: "text-loss", fill: "bg-loss" };
  }
  if (score < HIGH) {
    return { label: "Moderate conviction", text: "text-risk", fill: "bg-risk" };
  }
  return { label: "High conviction", text: "text-gain", fill: "bg-gain" };
}

/**
 * The full conviction module from the reference: heading with an info
 * affordance, the score as a large figure against "/ 100", a progress bar,
 * and the band read out in words underneath.
 *
 * The score renders inside this component, once. No screen restates it as a
 * separate number beside the bar — the figure, the bar and the label are one
 * widget, not three.
 */
export function ConvictionScore({
  score,
  heading = "Conviction Score",
  className,
}: {
  score: number;
  heading?: string | null;
  className?: string;
}) {
  const pct = Math.min(Math.max(score, 0), 100);
  const band = bandFor(score);

  // Fill from 0 on mount so the bar reads as a measurement being taken. Two
  // frames: the first commits width:0, the second sets the target — in a
  // single tick the transition collapses to a no-op.
  const [width, setWidth] = useState(0);
  useEffect(() => {
    let raf2 = 0;
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => setWidth(pct));
    });
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
    };
  }, [pct]);

  return (
    <div className={clsx("flex flex-col gap-sp-3", className)}>
      {heading && (
        <div className="flex items-center gap-sp-2">
          <h3 className="t-title text-ink">{heading}</h3>
          <span
            tabIndex={0}
            title={GLOSSARY.conviction}
            aria-label={`${heading}: ${GLOSSARY.conviction}`}
            className="inline-flex cursor-help items-center text-ink-faint transition-colors duration-[var(--dur-hover)] hover:text-ink-dim"
          >
            <Info size={16} />
          </span>
        </div>
      )}

      <div className="flex items-baseline gap-sp-2">
        <span className={clsx("t-figure", band.text)}>{Math.round(score)}</span>
        <span className="t-lead text-ink-faint">/ 100</span>
      </div>

      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-conviction-track"
        role="meter"
        aria-valuenow={Math.round(score)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Conviction ${Math.round(score)} out of 100`}
      >
        <div
          className={clsx(
            "h-full rounded-full transition-[width] duration-[var(--dur-meter)] ease-out motion-reduce:transition-none",
            band.fill,
          )}
          style={{ width: `${width}%` }}
        />
      </div>

      <p className={clsx("t-body font-medium", band.text)}>{band.label}</p>
    </div>
  );
}

/**
 * The same score with no heading and no read-out — for lists, where the
 * module above would be repeated twenty times and stop being a focal point.
 * Same bands, same colors, so a score means the same thing in both places.
 */
export function ConvictionBar({
  score,
  className,
  showValue = true,
}: {
  score: number;
  className?: string;
  showValue?: boolean;
}) {
  const pct = Math.min(Math.max(score, 0), 100);
  const band = bandFor(score);

  return (
    <div className={clsx("flex items-center gap-sp-3", className)}>
      <div
        className="h-1.5 min-w-[3.5rem] flex-1 overflow-hidden rounded-full bg-conviction-track"
        role="meter"
        aria-valuenow={Math.round(score)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Conviction ${Math.round(score)} out of 100`}
      >
        <div className={clsx("h-full rounded-full", band.fill)} style={{ width: `${pct}%` }} />
      </div>
      {showValue && (
        <span className={clsx("num-table w-7 shrink-0 text-right t-body font-semibold", band.text)}>
          {Math.round(score)}
        </span>
      )}
    </div>
  );
}
