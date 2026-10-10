import clsx from "clsx";
import type { Setup } from "../../types/dashboard";
import { orderContext, orderSentence } from "../../lib/orderText";
import { companyName } from "../../lib/tickers";
import { StatusPill } from "../ui/StatusPill";

const MAX_ITEMS = 5;

/**
 * The day's trades as a plain to-do list: what to do, in which name, how
 * much, at what limit, and one sentence on why. Nothing else. Clicking a
 * row selects it for the chart, plan and insight panels below.
 */
export function TodoList({ actions, selected, onSelect }: { actions: Setup[]; selected: string | null; onSelect: (t: string) => void }) {
  const items = actions.slice(0, MAX_ITEMS);
  if (items.length === 0) {
    return (
      <div className="px-sp-5 py-sp-6">
        <p className="t-body font-medium text-ink-dim">Nothing to do today.</p>
        <p className="mt-sp-1 t-meta text-ink-faint">No position crossed an exit trigger and no new name was sized. That is a result, not a gap.</p>
      </div>
    );
  }
  return (
    <ol className="divide-y divide-line">
      {items.map((s, i) => {
        const order = s.order;
        const isSelected = s.ticker === selected;
        const name = s.name ?? companyName(s.ticker);
        return (
          <li key={s.ticker}>
            <button
              type="button"
              onClick={() => onSelect(s.ticker)}
              aria-pressed={isSelected}
              className={clsx(
                "flex w-full items-start gap-sp-4 px-sp-5 py-sp-4 text-left transition-colors duration-[var(--dur-hover)]",
                isSelected ? "bg-accent-wash/60" : "hover:bg-inset",
              )}
            >
              <span className="num-table mt-[3px] w-5 shrink-0 t-meta text-ink-faint">{i + 1}.</span>
              <span className="shrink-0 pt-[2px]">
                <StatusPill tone={s.action === "BUY" ? "buy" : "sell"}>{s.action === "TRIM" ? "Sell / Trim" : s.action}</StatusPill>
              </span>
              <span className="min-w-0 flex-1">
                {order ? (
                  <>
                    <span className="block t-title text-ink">{orderSentence(order)}</span>
                    {name && <span className="block t-meta text-ink-faint">{name}</span>}
                    <span className="mt-[2px] block t-body text-ink-dim">
                      {orderContext(order)}
                      {s.reason ? ` ${s.reason.endsWith(".") ? s.reason : s.reason + "."}` : ""}
                    </span>
                  </>
                ) : (
                  <>
                    <span className="block t-title text-ink">{s.ticker}</span>
                    {name && <span className="block t-meta text-ink-faint">{name}</span>}
                  </>
                )}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
