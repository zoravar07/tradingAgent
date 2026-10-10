import { useMemo, useState } from "react";
import { ArrowClockwise, CaretDown, CheckCircle, Moon, Prohibit, Receipt, WarningOctagon } from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import clsx from "clsx";
import { fetchOrders } from "../api/client";
import type { OrderRow, RunRow } from "../types/screens";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { fmtDate, fmtDateTime } from "../lib/format";
import { GLOSSARY, TRIGGER_TERMS, explainTrigger } from "../lib/glossary";
import { humanizeEnum } from "../lib/humanize";
import { orderContext, orderSentence } from "../lib/orderText";
import { companyName } from "../lib/tickers";
import { useAsyncData } from "../lib/useAsyncData";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConvictionBar } from "../components/ui/ConvictionScore";
import { DetailBlock, Disclosure } from "../components/ui/Disclosure";
import { EmptyRow, ScreenShell, Section } from "../components/ui/ScreenShell";
import { StatusPill, Tag } from "../components/ui/StatusPill";
import { Term } from "../components/ui/Term";

const STATUS_META: Record<string, { tone: "gain" | "loss" | "accent" | "neutral"; label: string }> = {
  filled: { tone: "gain", label: "Filled" },
  proposed: { tone: "accent", label: "Proposed" },
  dismissed: { tone: "neutral", label: "Dismissed" },
};

const RUN_META: Record<string, { tone: "gain" | "loss" | "neutral"; icon: Icon; label: string }> = {
  succeeded: { tone: "gain", icon: CheckCircle, label: "Completed" },
  blocked: { tone: "loss", icon: Prohibit, label: "Blocked" },
  failed: { tone: "loss", icon: WarningOctagon, label: "Failed" },
  running: { tone: "neutral", icon: Moon, label: "Running" },
};

/** The same instruction proposed on consecutive runs, shown once with a count. */
interface Grouped {
  key: string;
  latest: OrderRow;
  first: OrderRow;
  times: number;
}

function dedupe(orders: OrderRow[]): Grouped[] {
  // orders arrive newest first. The pipeline re-proposes the same trade
  // every night until it is acted on, so a repeat — same ticker, action,
  // quantity and trigger, limit within 2% — folds into the newest copy,
  // which keeps its place in the list and carries the count and first date.
  const out: Grouped[] = [];
  for (const o of orders) {
    const match = out.find(
      (g) =>
        g.latest.ticker === o.ticker &&
        g.latest.action === o.action &&
        g.latest.quantity === o.quantity &&
        g.latest.trigger_type === o.trigger_type &&
        Math.abs(g.latest.limit_price - o.limit_price) / o.limit_price < 0.02,
    );
    if (match) {
      match.first = o;
      match.times += 1;
    } else {
      out.push({ key: `${o.id}`, latest: o, first: o, times: 1 });
    }
  }
  return out;
}

function ProposalCard({ group, index, firstTerms }: { group: Grouped; index: number; firstTerms: boolean }) {
  const o = group.latest;
  const meta = STATUS_META[o.status] ?? { tone: "neutral" as const, label: o.status };
  const name = companyName(o.ticker);
  const triggerTerm = o.trigger_type ? TRIGGER_TERMS[o.trigger_type] : undefined;
  return (
    <li className="animate-rise" style={{ "--stagger-index": index } as React.CSSProperties}>
      <Card tone={o.action === "SELL" ? "sell" : "buy"}>
        <div className="flex flex-col gap-sp-2 px-sp-5 py-sp-4">
          <div className="flex flex-wrap items-start justify-between gap-sp-3">
            <div className="min-w-0">
              <p className="t-title text-ink">{orderSentence(o)}</p>
              <p className="t-meta text-ink-faint">
                {o.ticker}
                {name ? ` · ${name}` : ""}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-sp-2">
              <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
              {group.times > 1 && (
                <Tag>
                  proposed {group.times} times, since {fmtDate(group.first.created_at)}
                </Tag>
              )}
            </div>
          </div>
          <p className="t-body text-ink-dim">
            {orderContext({ ...o, weight_pct: null })}{" "}
            {triggerTerm ? (
              <>
                Triggered by the {firstTerms ? <Term text={triggerTerm.text} definition={triggerTerm.definition} /> : triggerTerm.text}.{" "}
              </>
            ) : null}
            {explainTrigger(o.trigger_type)}
          </p>
          <div className="flex flex-wrap items-center gap-sp-3">
            <span className="t-meta text-ink-faint">
              {firstTerms ? <Term text="Conviction" definition={GLOSSARY.conviction} /> : "Conviction"}
            </span>
            <ConvictionBar score={o.conviction} className="w-40" />
            <span className="t-meta text-ink-faint">{fmtDateTime(o.created_at)}</span>
          </div>
        </div>
        <div className="border-t border-line bg-inset">
          <Disclosure label="Why this trade" openLabel="Hide the reasoning">
            <DetailBlock label="The reasoning at the time">{o.rationale || "No write-up was stored for this proposal."}</DetailBlock>
          </Disclosure>
        </div>
      </Card>
    </li>
  );
}

function TickerFilter({ tickers, selected, onChange }: { tickers: string[]; selected: Set<string>; onChange: (next: Set<string>) => void }) {
  const [open, setOpen] = useState(false);
  const label = selected.size === 0 ? "All names" : selected.size === 1 ? [...selected][0] : `${selected.size} names`;
  return (
    <div className="relative">
      <Button variant="secondary" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="listbox">
        {label}
        <CaretDown size={13} weight="bold" className={clsx("transition-transform", open && "rotate-180")} />
      </Button>
      {open && (
        <div role="listbox" aria-multiselectable className="absolute right-0 z-20 mt-sp-2 max-h-80 w-56 overflow-auto rounded-inner border border-line bg-surface p-sp-2 shadow-card">
          <button type="button" className="pressable w-full rounded-chip px-sp-2 py-[6px] text-left t-meta text-ink-dim hover:bg-inset" onClick={() => onChange(new Set())}>
            Show all
          </button>
          {tickers.map((t) => (
            <label key={t} className="flex cursor-pointer items-center gap-sp-2 rounded-chip px-sp-2 py-[6px] t-body text-ink hover:bg-inset">
              <input
                type="checkbox"
                checked={selected.has(t)}
                onChange={(e) => {
                  const next = new Set(selected);
                  if (e.target.checked) next.add(t);
                  else next.delete(t);
                  onChange(next);
                }}
              />
              <span className="font-medium">{t}</span>
              {companyName(t) && <span className="truncate t-meta text-ink-faint">{companyName(t)}</span>}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function RunLine({ run }: { run: RunRow }) {
  const meta = RUN_META[run.status] ?? { tone: "neutral" as const, icon: Moon, label: run.status };
  return (
    <li className="flex flex-wrap items-center gap-sp-3 py-sp-3">
      <meta.icon size={17} weight="fill" className="shrink-0 text-ink-faint" />
      <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
      <span className="t-meta text-ink-faint">{fmtDateTime(run.started_at)}</span>
      <span className="t-body text-ink-dim">
        {run.proposal_count === 0 ? "No trade was proposed." : `${run.proposal_count} trade${run.proposal_count === 1 ? "" : "s"} proposed.`}
      </span>
      {run.risk_events.map((e) => (
        <Tag key={e.type}>
          {humanizeEnum(e.type)} <span className="num-table font-semibold">{e.count}</span>
        </Tag>
      ))}
      {run.error && <span className="t-meta text-loss">{run.error}</span>}
    </li>
  );
}

/**
 * Every trade the system has proposed, newest day first, with the nightly
 * repeats of an unacted trade folded into one line. Filter by name from a
 * list built from the trades themselves.
 */
export function OrdersScreen() {
  const { state, reload } = useAsyncData(fetchOrders, "Unexpected error loading orders.");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const data = state.kind === "loaded" ? state.data : null;

  const tickers = useMemo(() => (data ? [...new Set(data.orders.map((o) => o.ticker))].sort() : []), [data]);
  const groups = useMemo(() => (data ? dedupe(data.orders.filter((o) => selected.size === 0 || selected.has(o.ticker))) : []), [data, selected]);
  const byDay = useMemo(() => {
    const days = new Map<string, Grouped[]>();
    for (const g of groups) {
      const day = g.latest.created_at.slice(0, 10);
      days.set(day, [...(days.get(day) ?? []), g]);
    }
    return [...days.entries()];
  }, [groups]);

  return (
    <ScreenShell
      title="Proposals"
      subtitle="Every trade the system has suggested, by day."
      actions={
        <Button onClick={reload} disabled={state.kind === "loading"}>
          <ArrowClockwise size={14} className={state.kind === "loading" ? "animate-spin" : ""} />
          Refresh
        </Button>
      }
    >
      {state.kind === "loading" && <LoadingSkeleton />}
      {state.kind === "error" && <ErrorPanel message={state.message} onRetry={reload} />}

      {data && (
        <>
          <Section
            title="By day"
            count={groups.length}
            icon={<Receipt size={19} weight="fill" className="text-accent" />}
            actions={tickers.length > 0 && <TickerFilter tickers={tickers} selected={selected} onChange={setSelected} />}
          >
            {groups.length === 0 ? (
              <EmptyRow label="No proposals yet." hint="They appear here as soon as a run suggests a trade." />
            ) : (
              <div className="flex flex-col gap-sp-5">
                {byDay.map(([day, items], di) => (
                  <div key={day} className="flex flex-col gap-sp-3">
                    <h3 className="t-body font-semibold text-ink">{fmtDate(`${day}T00:00:00`)}</h3>
                    <ol className="flex flex-col gap-sp-3">
                      {items.map((g, i) => (
                        <ProposalCard key={g.key} group={g} index={i} firstTerms={di === 0 && i === 0} />
                      ))}
                    </ol>
                  </div>
                ))}
              </div>
            )}
          </Section>

          <Section title="Runs" count={data.runs.length} subtitle="What each run did, including the ones that proposed nothing.">
            <Card>
              <ol className="divide-y divide-line px-sp-5">
                {data.runs.map((r) => (
                  <RunLine key={r.run_id} run={r} />
                ))}
              </ol>
            </Card>
          </Section>
        </>
      )}
    </ScreenShell>
  );
}
