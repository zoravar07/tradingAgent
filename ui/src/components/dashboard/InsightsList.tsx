import { Buildings, ChartLineUp, Newspaper, Warning } from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import type { Insight } from "../../types/dashboard";

const ROWS: { key: keyof Insight; label: string; icon: Icon; tone: string }[] = [
  { key: "technical", label: "Technical", icon: ChartLineUp, tone: "bg-gain-wash text-gain" },
  { key: "fundamental", label: "Fundamental", icon: Buildings, tone: "bg-accent-wash text-accent" },
  { key: "news", label: "News", icon: Newspaper, tone: "bg-risk-wash text-risk" },
  { key: "risk", label: "Risk", icon: Warning, tone: "bg-loss-wash text-loss" },
];

/** Four one-liners for the selected name, each from a persisted field. */
export function InsightsList({ ticker, insight }: { ticker: string | null; insight: Insight | null }) {
  if (!ticker) {
    return <p className="px-sp-5 py-sp-6 t-body text-ink-faint">Select a name to see its insights.</p>;
  }
  return (
    <ul className="divide-y divide-line">
      {ROWS.map(({ key, label, icon: RowIcon, tone }) => {
        const text = insight?.[key] ?? null;
        return (
          <li key={key} className="flex items-start gap-sp-3 px-sp-5 py-sp-3">
            <span aria-hidden className={`mt-[2px] flex h-7 w-7 shrink-0 items-center justify-center rounded-chip ${tone}`}>
              <RowIcon size={15} weight="bold" />
            </span>
            <div className="min-w-0">
              <p className="t-meta font-medium text-ink">{label}</p>
              <p className={`t-meta ${text ? "text-ink-dim" : "text-ink-faint"}`}>
                {text ?? "Not available for this name in the latest run."}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
