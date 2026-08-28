import { useState } from "react";
import { CaretDown, Check, Copy, Lightning } from "@phosphor-icons/react";
import type { ActionItem, OrderProposal } from "../../types/briefing";
import { fmtUsd, fmtUsd2 } from "../../lib/format";
import { StatusPill } from "../StatusPill";
import { ConvictionMeter } from "../ConvictionMeter";
import { ClampText } from "../ClampText";
import { EmptySection, SectionShell } from "./SectionShell";

function CopyDetailsButton({ order }: { order: OrderProposal }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    const text = `${order.action} ${order.ticker} ${order.quantity} ${order.order_type} ${fmtUsd2(order.limit_price)}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard permission denied or unavailable — a convenience action
      // failing silently beats surfacing an error banner over it.
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="flex shrink-0 items-center gap-1.5 rounded-md border border-[var(--color-hairline-strong)] bg-[var(--color-panel)] px-2.5 py-1.5 text-xs font-medium text-[var(--color-ink-dim)] transition-colors hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)] active:scale-[0.98]"
    >
      {copied ? <Check size={12} className="text-[var(--color-gain)]" /> : <Copy size={12} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function ActionCard({ item }: { item: ActionItem }) {
  const { order } = item;
  const isBuy = order.action === "BUY";
  const wash = isBuy
    ? "bg-[var(--color-gain-wash)] border-[var(--color-gain)]/25"
    : "bg-[var(--color-loss-wash)] border-[var(--color-loss)]/25";

  return (
    <div className={`rounded-xl border p-4 ${wash}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill tone={isBuy ? "gain" : "loss"}>
            {order.action}
            {order.is_trim ? " · trim" : ""}
          </StatusPill>
          <span className="num text-xl font-bold text-[var(--color-ink)]">{order.ticker}</span>
        </div>
        <CopyDetailsButton order={order} />
      </div>

      <p className="mt-2 text-[15px] font-semibold text-[var(--color-ink)]">{item.headline}</p>
      {item.thesis_summary && (
        <ClampText text={item.thesis_summary} lines={1} className="mt-1 text-sm text-[var(--color-ink-dim)]" />
      )}

      <div className="mt-3 max-w-xs">
        <ConvictionMeter score={order.conviction} size="sm" />
      </div>

      <div className="num mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--color-ink-faint)]">
        <span>{order.quantity} sh</span>
        <span>{order.order_type} {fmtUsd2(order.limit_price)}</span>
        <span>~{fmtUsd(order.estimated_cost_usd)}</span>
        <span>{order.weight_pct.toFixed(1)}% of NAV</span>
      </div>

      {item.bear_case && (
        <details className="group mt-2.5 border-t border-[var(--color-hairline)] pt-2.5">
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
    <SectionShell
      title="Actions today"
      subtitle="Trade-ready orders — copy the numbers into IBKR yourself."
      count={actions.length}
      accent={actions.length > 0}
      icon={Lightning}
    >
      {actions.length === 0 ? (
        <EmptySection label="No proposals this run." />
      ) : (
        <div className="flex flex-col gap-3">
          {actions.map((item, i) => (
            <ActionCard key={`${item.order.ticker}-${i}`} item={item} />
          ))}
        </div>
      )}
    </SectionShell>
  );
}
