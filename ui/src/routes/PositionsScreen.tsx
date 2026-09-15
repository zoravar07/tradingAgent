import { ArrowClockwise, ChartBar, Question, WarningCircle } from "@phosphor-icons/react";
import clsx from "clsx";
import { useId, useMemo, useState } from "react";
import { fetchDashboard, fetchPositions } from "../api/client";
import type { DashboardResponse, Holding, HoldingAction } from "../types/dashboard";
import type { PositionRow } from "../types/screens";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { fmtDateTime, fmtNum, fmtPct, fmtPctPlain, fmtUsd, fmtUsd2 } from "../lib/format";
import { GLOSSARY } from "../lib/glossary";
import { orderContext, orderSentence } from "../lib/orderText";
import { companyName } from "../lib/tickers";
import { useAsyncData } from "../lib/useAsyncData";
import { Button } from "../components/ui/Button";
import { Callout } from "../components/ui/Callout";
import { Card, CardHeader } from "../components/ui/Card";
import { ConvictionBar } from "../components/ui/ConvictionScore";
import { EmptyRow, ScreenShell, Section } from "../components/ui/ScreenShell";
import { StatRow } from "../components/ui/StatRow";
import { StatusPill } from "../components/ui/StatusPill";
import { Term } from "../components/ui/Term";

type Urgency = 3 | 2 | 1 | 0;

const URGENCY_META: Record<Urgency, { label: string; tone: "loss" | "risk" | "accent" | "neutral"; iconTone: string; why: string }> = {
  3: { label: "Act today", tone: "loss", iconTone: "text-loss", why: "A trade is proposed for this position today." },
  2: { label: "Watch closely", tone: "risk", iconTone: "text-risk", why: "Conviction is below your floor, or the price is within 5% of its trailing stop." },
  1: { label: "Keep an eye on", tone: "accent", iconTone: "text-accent", why: "Conviction is middling, or the position wasn't researched this run." },
  0: { label: "Fine", tone: "neutral", iconTone: "text-ink-faint", why: "No rule is close to firing." },
};

const ACTION_META: Record<HoldingAction, { label: string; tone: "buy" | "sell" | "neutral" }> = {
  BUY: { label: "Buy more", tone: "buy" },
  SELL: { label: "Sell", tone: "sell" },
  TRIM: { label: "Trim", tone: "sell" },
  HOLD: { label: "Hold", tone: "neutral" },
};

interface Row {
  p: PositionRow;
  h: Holding | undefined;
  action: HoldingAction;
  urgency: Urgency;
  why: string;
  order: Extract<DashboardResponse, { status: "ok" }>["setups"][number]["order"] | null;
}

/** The urgency tier and the one specific reason it landed there. */
function urgencyFor(p: PositionRow, h: Holding | undefined): { urgency: Urgency; why: string } {
  if (h && h.action !== "HOLD") return { urgency: 3, why: URGENCY_META[3].why };
  const conviction = h?.conviction ?? p.conviction_now;
  if (conviction !== null && conviction < 40) return { urgency: 2, why: `Conviction is ${conviction.toFixed(0)}, below your floor of 40.` };
  if (p.distance_to_trailing_stop_pct !== null && p.distance_to_trailing_stop_pct < 5) return { urgency: 2, why: "The price is within 5% of its trailing stop." };
  if (conviction === null) return { urgency: 1, why: "No conviction score yet." };
  if (p.no_research_coverage) return { urgency: 1, why: "This position was not researched in the latest run, so its score may be stale." };
  if (conviction < 50) return { urgency: 1, why: `Conviction is ${conviction.toFixed(0)}, a middling score.` };
  return { urgency: 0, why: URGENCY_META[0].why };
}

/** Everything that explains why a row landed on its recommended action —
 * hidden behind the "?" toggle by default, so the default view stays
 * ticker/value/conviction, not a wall of reasoning prose. */
function Reason({ row, firstTerms }: { row: Row; firstTerms: boolean }) {
  const { p, why, order } = row;
  return (
    <p className="t-body text-ink-dim">
      {order ? `${orderSentence(order)} ${orderContext(order)}`.trim() : why}{" "}
      {p.distance_to_trailing_stop_pct !== null && (
        <>
          The price is {fmtPctPlain(Math.abs(p.distance_to_trailing_stop_pct))} {p.distance_to_trailing_stop_pct <= 0 ? "below" : "above"} its{" "}
          {firstTerms ? <Term text="trailing stop" definition={GLOSSARY.trailingStop} /> : "trailing stop"}.{" "}
        </>
      )}
      {p.no_research_coverage && !why.startsWith("This position") && "This position was not researched in the latest run, so its score may be stale."}
    </p>
  );
}

function PositionLine({ row, index, firstTerms }: { row: Row; index: number; firstTerms: boolean }) {
  const { p, h, action, urgency } = row;
  const name = h?.name ?? companyName(p.ticker);
  const pnl = p.unrealized_pnl_pct;
  const conviction = h?.conviction ?? p.conviction_now;
  const u = URGENCY_META[urgency];
  const a = ACTION_META[action];
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <li className="animate-rise" style={{ "--stagger-index": index } as React.CSSProperties}>
      <Card tone={action === "HOLD" ? "neutral" : a.tone === "buy" ? "buy" : "sell"}>
        <div className="flex flex-col gap-sp-3 px-sp-5 py-sp-4">
          <CardHeader
            className="px-0 pt-0"
            trailing={
              <div className="flex shrink-0 items-center gap-sp-2">
                <StatusPill tone={a.tone}>{a.label}</StatusPill>
                <button
                  type="button"
                  onClick={() => setOpen((v) => !v)}
                  aria-expanded={open}
                  aria-controls={panelId}
                  aria-label={`Why ${a.label.toLowerCase()}?`}
                  className={clsx(
                    "pressable flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line transition-colors duration-[var(--dur-hover)] hover:border-line-strong hover:bg-inset-strong",
                    u.iconTone,
                  )}
                >
                  <Question size={13} weight="bold" />
                </button>
              </div>
            }
          >
            <div className="min-w-0">
              <p className="t-title text-ink">{p.ticker}</p>
              {name && <p className="mt-[2px] t-body text-ink-faint">{name}</p>}
            </div>
          </CardHeader>

          <div id={panelId} className="expandable" data-open={open}>
            <div>
              <Reason row={row} firstTerms={firstTerms} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-sp-5 gap-y-sp-2 sm:grid-cols-4">
            <div>
              <p className="t-meta text-ink-faint">Value</p>
              <p className="num-table t-body font-medium text-ink">
                {p.value_usd === null ? "—" : fmtUsd(p.value_usd)}
                {p.weight_pct !== null && <span className="t-meta text-ink-faint"> · {fmtPctPlain(p.weight_pct)}</span>}
              </p>
            </div>
            <div>
              <p className="t-meta text-ink-faint">Gain or loss</p>
              <p className={clsx("num-table t-body font-medium", pnl === null ? "text-ink-faint" : pnl >= 0 ? "text-gain" : "text-loss")}>
                {pnl === null ? "—" : fmtPct(pnl)}
              </p>
            </div>
            <div>
              <p className="t-meta text-ink-faint">You hold</p>
              <p className="num-table t-body font-medium text-ink">
                {fmtNum(p.qty)} {p.qty === 1 ? "share" : "shares"} <span className="t-meta text-ink-faint">at {fmtUsd2(p.avg_cost)} average</span>
              </p>
            </div>
            <div>
              <p className="t-meta text-ink-faint">
                {firstTerms ? <Term text="Conviction" definition={GLOSSARY.conviction} /> : "Conviction"}
              </p>
              {conviction === null ? (
                <p className="t-meta text-ink-faint">no score yet</p>
              ) : (
                <ConvictionBar score={conviction} className="mt-[6px]" />
              )}
            </div>
          </div>
        </div>
      </Card>
    </li>
  );
}

/**
 * Every holding with what to do about it. Rows are sorted by urgency —
 * anything with a trade proposed today first, then names whose sell rules
 * are close, then the rest — and each carries the recommended action,
 * the conviction score, and the size of the position.
 */
export function PositionsScreen() {
  const positions = useAsyncData(fetchPositions, "Unexpected error loading positions.");
  const dashboard = useAsyncData(fetchDashboard, "Unexpected error loading recommendations.");
  const loading = positions.state.kind === "loading" || dashboard.state.kind === "loading";
  const reload = () => {
    positions.reload();
    dashboard.reload();
  };
  const data = positions.state.kind === "loaded" ? positions.state.data : null;
  const dash = dashboard.state.kind === "loaded" && dashboard.state.data.status === "ok" ? dashboard.state.data : null;
  const error = positions.state.kind === "error" ? positions.state.message : dashboard.state.kind === "error" ? dashboard.state.message : null;

  const rows: Row[] = useMemo(() => {
    if (!data) return [];
    const holdings = new Map((dash?.holdings ?? []).map((h) => [h.ticker, h]));
    const orders = new Map((dash?.setups ?? []).filter((s) => s.order).map((s) => [s.ticker, s.order]));
    return data.positions
      .map((p) => {
        const h = holdings.get(p.ticker);
        const action: HoldingAction = h?.action ?? "HOLD";
        return { p, h, action, ...urgencyFor(p, h), order: orders.get(p.ticker) ?? null };
      })
      .sort((a, b) => b.urgency - a.urgency || (b.p.value_usd ?? 0) - (a.p.value_usd ?? 0));
  }, [data, dash]);

  const bookValue = rows.reduce((sum, r) => sum + (r.p.value_usd ?? 0), 0);
  const unpriced = rows.filter((r) => r.p.value_usd === null);
  const urgent = rows.filter((r) => r.urgency === 3).length;

  return (
    <ScreenShell
      title="Positions"
      subtitle="Everything you hold, most urgent first, with what to do about each."
      actions={
        <Button onClick={reload} disabled={loading}>
          <ArrowClockwise size={14} className={loading ? "animate-spin" : ""} />
          Refresh
        </Button>
      }
    >
      {loading && <LoadingSkeleton />}
      {!loading && error && <ErrorPanel message={error} onRetry={reload} />}

      {!loading && data && (
        <>
          <Card>
            <div className="px-sp-6 py-sp-5">
              <StatRow
                stats={[
                  { label: "Value of holdings", value: fmtUsd(bookValue), hint: "not counting cash" },
                  { label: "Positions", value: String(rows.length) },
                  { label: "Need action today", value: String(urgent), tone: urgent > 0 ? "loss" : undefined },
                  { label: "Priced", value: data.priced_at ? fmtDateTime(data.priced_at) : "—", hint: "at the last run" },
                ]}
              />
            </div>
          </Card>

          {unpriced.length > 0 && (
            <Callout icon={WarningCircle} tone="risk" title={`${unpriced.length} holding${unpriced.length === 1 ? "" : "s"} could not be priced in the last run.`}>
              {unpriced.map((r) => r.p.ticker).join(", ")} — the number of shares and the average cost are from your book; value and score are left blank rather than guessed.
            </Callout>
          )}

          <Section title="Holdings" count={rows.length} icon={<ChartBar size={19} weight="fill" className="text-accent" />}>
            {rows.length === 0 ? (
              <EmptyRow label="No positions on file." hint="Positions are synced from IBKR before every run." />
            ) : (
              <ol className="flex flex-col gap-sp-3">
                {rows.map((r, i) => (
                  <PositionLine key={r.p.ticker} row={r} index={i} firstTerms={i === 0} />
                ))}
              </ol>
            )}
          </Section>
        </>
      )}
    </ScreenShell>
  );
}
