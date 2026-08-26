import { CaretDown } from "@phosphor-icons/react";
import type { ActionItem } from "../../types/briefing";
import { fmtUsd, fmtUsd2 } from "../../lib/format";
import { StatusPill } from "../StatusPill";
import { EmptySection, SectionShell } from "./SectionShell";

function ActionRow({ item }: { item: ActionItem }) {
  const { order } = item;
  return (
    <div className="border-b border-[var(--color-hairline)] py-3 last:border-0 last:pb-0 first:pt-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <StatusPill tone={order.action === "BUY" ? "gain" : "loss"}>
          {order.action}
          {order.is_trim ? " · trim" : ""}
        </StatusPill>
        <span className="num text-sm font-semibold text-[var(--color-ink)]">{order.ticker}</span>
        <span className="num text-sm text-[var(--color-ink-dim)]">
          {order.quantity} sh @ {order.order_type} {fmtUsd2(order.limit_price)}
        </span>
        <span className="num text-sm text-[var(--color-ink-dim)]">
          ~{fmtUsd(order.estimated_cost_usd)}
        </span>
        <span className="num text-sm text-[var(--color-ink-dim)]">{order.weight_pct.toFixed(1)}% of NAV</span>
        <span className="ml-auto num text-sm font-medium text-[var(--color-accent)]">
          conviction {order.conviction.toFixed(0)}
        </span>
      </div>

      <p className="mt-1.5 text-sm text-[var(--color-ink)]">{item.headline}</p>
      {item.thesis_summary && (
        <p className="mt-0.5 text-sm text-[var(--color-ink-dim)]">{item.thesis_summary}</p>
      )}

      {item.bear_case && (
        <details className="group mt-1.5">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-[var(--color-ink-faint)] hover:text-[var(--color-ink-dim)]">
            <CaretDown size={11} className="transition-transform group-open:rotate-180" />
            Bear case
          </summary>
          <p className="mt-1 pl-4 text-sm text-[var(--color-ink-dim)]">{item.bear_case}</p>
        </details>
      )}
    </div>
  );
}

export function ActionsSection({ actions }: { actions: ActionItem[] }) {
  return (
    <SectionShell title="Actions today" count={actions.length}>
      {actions.length === 0 ? (
        <EmptySection label="No proposals this run." />
      ) : (
        actions.map((item, i) => <ActionRow key={`${item.order.ticker}-${i}`} item={item} />)
      )}
    </SectionShell>
  );
}
