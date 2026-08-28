import { useState } from "react";
import { CaretDown, Check, Copy } from "@phosphor-icons/react";
import type { ActionItem, OrderProposal } from "../../types/briefing";
import { fmtUsd, fmtUsd2 } from "../../lib/format";
import { StatusPill } from "../StatusPill";
import { HelpTip } from "../HelpTip";
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
      className="flex shrink-0 items-center gap-1 rounded-md border border-[var(--color-hairline-strong)] px-2 py-1 text-xs font-medium text-[var(--color-ink-dim)] transition-colors hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)] active:scale-[0.98]"
    >
      {copied ? <Check size={11} className="text-[var(--color-gain)]" /> : <Copy size={11} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function ActionRow({ item }: { item: ActionItem }) {
  const { order } = item;
  const stripe = order.action === "BUY" ? "border-l-[var(--color-gain)]" : "border-l-[var(--color-loss)]";

  return (
    <div
      className={`border-b-[var(--color-hairline)] border-l-2 ${stripe} border-b py-3 pl-3 last:border-b-0 first:pt-0`}
    >
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
        <div className="ml-auto flex items-center gap-2.5">
          <span className="num flex items-center gap-1 text-sm font-medium text-[var(--color-accent)]">
            conviction {order.conviction.toFixed(0)}
            <HelpTip text="A 0–100 confidence score from the research agent. Higher means stronger evidence for the thesis." />
          </span>
          <CopyDetailsButton order={order} />
        </div>
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
    <SectionShell
      title="Actions today"
      subtitle="Trade-ready orders — copy the numbers into IBKR yourself."
      count={actions.length}
      accent={actions.length > 0}
    >
      {actions.length === 0 ? (
        <EmptySection label="No proposals this run." />
      ) : (
        actions.map((item, i) => <ActionRow key={`${item.order.ticker}-${i}`} item={item} />)
      )}
    </SectionShell>
  );
}
